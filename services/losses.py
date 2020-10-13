"""This module contains losses to be used during training.

Losses:
    - ArcLoss
    - Discriminator Loss
    - Generator Loss
    - Joint Loss
"""
import logging

import tensorflow as tf
from training.metrics import (
    apply_softmax,
    compute_binary_crossentropy,
    compute_categorical_crossentropy,
    compute_euclidean_distance,
    compute_l1_loss,
    distributed_sum_over_batch_size,
)
from training.vgg import create_vgg_model


class Loss:
    def __init__(
        self,
        batch_size: int,
        train_summary_writer,
        weight: float = 0.1,
        scale: float = 64.0,
        margin: float = 0.5,
    ):
        self.LOGGER = logging.getLogger(__name__)
        self.train_summary_writer = train_summary_writer

        self.batch_size = batch_size
        self.vgg = create_vgg_model()
        self.weight = weight
        self.scale = scale
        self.margin = margin

        self._compute_categorical_crossentropy = distributed_sum_over_batch_size(
            batch_size
        )(compute_categorical_crossentropy)

    @tf.function
    def _compute_perceptual_loss(self, super_resolution, ground_truth) -> float:
        fake = self.vgg(super_resolution)
        real = self.vgg(ground_truth)
        return self.weight * compute_euclidean_distance(fake, real)

    @tf.function
    def _generator_loss(self, sr_predictions, ground_truth_predictions) -> float:
        super_resolution_mean = tf.math.reduce_mean(sr_predictions)
        groud_truth_mean = tf.math.reduce_mean(ground_truth_predictions)

        groud_truth_average = ground_truth_predictions - super_resolution_mean
        super_resolution_average = sr_predictions - groud_truth_mean

        # Reshaping tensor from shape [batch_size, 1] to [1, batch_size],
        # because with the original shape `apply_softmax` was buggy and was
        # outputting an array of 1's like [1, 1, 1, 1, ...].
        groud_truth_average = self.reshape_tensor_to_softmax(groud_truth_average)
        super_resolution_average = self.reshape_tensor_to_softmax(
            super_resolution_average
        )

        gt_relativistic_average = compute_binary_crossentropy(
            tf.zeros_like(groud_truth_average),
            apply_softmax(groud_truth_average),
        )
        sr_relativistic_average = compute_binary_crossentropy(
            tf.ones_like(super_resolution_average),
            apply_softmax(super_resolution_average),
        )
        return tf.math.reduce_mean(
            [gt_relativistic_average, sr_relativistic_average], name="generator_loss"
        )

    # @tf.function
    def _compute_generator_loss(
        self,
        super_resolution,
        ground_truth,
        discriminator_sr_predictions,
        discriminator_gt_predictions,
        step,
    ) -> float:
        perceptual_loss = self._compute_perceptual_loss(super_resolution, ground_truth)
        generator_loss = self._generator_loss(
            discriminator_sr_predictions, discriminator_gt_predictions
        )
        l1_loss = self.weight * compute_l1_loss(super_resolution, ground_truth)

        with self.train_summary_writer.as_default():
            tf.summary.scalar(
                "Perceptual Loss",
                perceptual_loss,
                step=step,
            )
            tf.summary.scalar(
                "Generator Loss",
                generator_loss,
                step=step,
            )
            tf.summary.scalar(
                "L1 Loss",
                l1_loss,
                step=step,
            )

        return tf.math.reduce_sum(
            [perceptual_loss, generator_loss, l1_loss], name="sr_loss"
        )

    # def _compute_arcloss(
    #    self, embeddings, ground_truth, num_classes: int, net_type: str = "syn"
    # ) -> float:
    #    """Compute the ArcLoss.
    #
    #    ### Parameters
    #        embeddings: Batch of Embedding vectors where loss will be calculated on.
    #        ground_truth: Batch of Ground Truth classes.
    #        fc_weights: Weights extracted from the last Fully Connected layer of\
    #        the network (Embedding layer).
    #        num_classes: Total number of classes in the dataset.
    #        scale:
    #        margin:
    #
    #    ### Returns
    #        The loss value."""
    #    original_target_embeddings = embeddings
    #    cos_theta = original_target_embeddings / self.scale
    #    theta = tf.acos(cos_theta)
    #
    #    z = theta + self.margin
    #    marginal_target_embeddings = tf.cos(z) * self.scale
    #
    #    one_hot_vector = tf.one_hot(ground_truth, depth=num_classes)
    #
    #    difference = marginal_target_embeddings - original_target_embeddings
    #    new_one_hot = one_hot_vector * difference
    #
    #    softmax_output = apply_softmax(original_target_embeddings + new_one_hot)
    #    return self._compute_categorical_crossentropy(softmax_output, one_hot_vector)

    # @tf.function
    def compute_joint_loss(
        self,
        super_resolution_images,
        ground_truth_images,
        discriminator_sr_predictions,
        discriminator_gt_predictions,
        synthetic_face_recognition,
        step,
        natural_face_recognition=None,
    ) -> float:
        """Computes the Joint Loss for Super Resolution Face Recognition, using\
    outputs from Synthetic SRFR and Natural SRFR, or using outputs from Synthetic\
    SRFR only.

        Parameters
        ----------
            super_resolution_images: Outputs from the Super Resolution Generator.
            ground_truth_images: High Resolution inputs.
            synthetic_face_recognition: A tuple of (embeddings, predictions, ground_truth_\
    classes, fc_weights, num_classes) from the Synthetic SRFR.
            natural_face_recognition: A tuple of (embeddings, ground_truth_\
    classes, fc_weights, num_classes) from the Natural SRFR.
            weight: Weight for the SR Loss.
            scale: Scale parameter for ArcLoss.
            margin: Margin penalty for ArcLoss.

        Returns
        -------
            The loss value.
        """
        super_resolution_loss = self._compute_generator_loss(
            super_resolution_images,
            ground_truth_images,
            discriminator_sr_predictions,
            discriminator_gt_predictions,
            step,
        )
        synthetic_face_recognition_loss = self._compute_categorical_crossentropy(
            synthetic_face_recognition[1],
            synthetic_face_recognition[2],
        )
        if natural_face_recognition:
            natural_face_recognition_loss = self._compute_categorical_crossentropy(
                synthetic_face_recognition[1],
                synthetic_face_recognition[2],
            )
            fr_loss = synthetic_face_recognition_loss + natural_face_recognition_loss
            return fr_loss + self.weight * super_resolution_loss

        with self.train_summary_writer.as_default():
            tf.summary.scalar(
                "SR Generator",
                super_resolution_loss,
                step=step,
            )
            tf.summary.scalar(
                "CrossEntropy",
                synthetic_face_recognition_loss,
                step=step,
            )

        return synthetic_face_recognition_loss + self.weight * super_resolution_loss

    @tf.function
    def compute_discriminator_loss(
        self, sr_predictions, ground_truth_predictions
    ) -> float:
        super_resolution_mean = tf.math.reduce_mean(sr_predictions)
        groud_truth_mean = tf.math.reduce_mean(ground_truth_predictions)

        groud_truth_average = ground_truth_predictions - super_resolution_mean
        super_resolution_average = sr_predictions - groud_truth_mean

        # Reshaping tensor from shape [batch_size, 1] to [1, batch_size],
        # because with the original shape `apply_softmax` was buggy and was
        # outputting an array of 1's like [1, 1, 1, 1, ...].
        groud_truth_average = self.reshape_tensor_to_softmax(groud_truth_average)
        super_resolution_average = self.reshape_tensor_to_softmax(
            super_resolution_average
        )

        gt_relativistic_average = compute_binary_crossentropy(
            tf.ones_like(groud_truth_average),
            apply_softmax(groud_truth_average),
        )
        sr_relativistic_average = compute_binary_crossentropy(
            tf.zeros_like(super_resolution_average),
            apply_softmax(super_resolution_average),
        )
        return tf.math.reduce_mean(
            [gt_relativistic_average, sr_relativistic_average],
            name="discriminator_loss",
        )

    @staticmethod
    @tf.function
    def reshape_tensor_to_softmax(tensor):
        return tf.expand_dims(tf.squeeze(tensor), axis=0)
