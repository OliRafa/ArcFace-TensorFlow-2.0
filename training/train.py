"""This module contains functions used for training."""
import tensorflow as tf
from training.losses import (
    compute_arcloss,
    compute_discriminator_loss,
    compute_joint_loss,
)

# Terminar a parte do Discriminator nas duas funções.

@tf.function
def generate_num_epochs(iterations, len_dataset, batch_size):
    train_size = tf.math.ceil(len_dataset / batch_size)
    return tf.cast(tf.math.ceil(iterations / train_size), dtype=tf.int32)

@tf.function
def adjust_learning_rate(current_learning_rate: float, epoch: int = 1) -> float:
    """Adjusts learning rate based on the current value and a giving epoch.

    ### Parameters
        current_learning_rate: Current value for the learning rate.
        epoch: Epoch number.

    ### Returns
        New value for the learning rate.
    """
    if epoch % 20 == 0:
        return current_learning_rate / 10
    return current_learning_rate

@tf.function
def _train_step(
        model,
        images,
        classes,
        num_classes,
        scale: float,
        margin: float,
    ):
    """Does a training step

    ### Parameters:
        model:
        images: Batch of images for training.
        classes: Batch of classes to compute the loss.
        num_classes: Total number of classes in the dataset.
        s:
        margin:

    ### Returns:
        (loss_value, grads) The loss value and the gradients to be optimized.
    """
    with tf.GradientTape() as tape:
        embeddings, fc_weights = model(images)
        loss_value = compute_arcloss(
            embeddings,
            classes,
            fc_weights,
            num_classes,
            scale,
            margin
        )
    grads = tape.gradient(loss_value, model.trainable_weights)
    return loss_value, grads

@tf.function
def train_model(
        model,
        dataset,
        num_classes,
        batch_size,
        optimizer,
        train_loss_function,
        scale: float,
        margin: float,
    ) -> float:
    """Train the model using the given dataset, compute the loss_function and\
 apply the optimizer.

    ### Parameters:
        model:
        dataset:
        num_classes:
        batch_size:
        optimizer:
        train_loss_function:
        scale:
        margin:

    ### Returns:
        The loss value.
    """
    for step, (image_batch, class_batch) in enumerate(dataset):
        loss_value, grads = _train_step(
            model,
            image_batch,
            class_batch,
            num_classes,
            scale,
            margin
        )
        optimizer.apply_gradients(zip(grads, model.trainable_weights))
        if step % 200 == 0:
            print('Training loss (for one batch) at step {}: {}'.format(
                step + 1,
                float(loss_value)
            ))
            print('Seen so far: {} samples'.format((step + 1) * batch_size))
    return train_loss_function(loss_value)

@tf.function
def _train_step_synthetic_only(
        srfr_model,
        sr_discriminator_model,
        low_resolution_batch,
        groud_truth_batch,
        ground_truth_classes,
        num_classes,
        weight: float,
        scale: float,
        margin: float,
    ):
    """Does a training step

    ### Parameters:
        model:
        images: Batch of images for training.
        classes: Batch of classes to compute the loss.
        num_classes: Total number of classes in the dataset.
        s:
        margin:

    ### Returns:
        (srfr_loss, srfr_grads, discriminator_loss, discriminator_grads)\
 The loss value and the gradients for SRFR network, as well as the loss value\
 and the gradients for the Discriminative network.
    """
    with tf.GradientTape() as srfr_tape, \
        tf.GradientTape() as discriminator_tape:
        (
            super_resolution_images,
            embeddings,
            fc_weights,
        ) = srfr_model(low_resolution_batch)
        discriminator_sr_predictions = sr_discriminator_model(super_resolution_images)
        discriminator_gt_predictions = sr_discriminator_model(groud_truth_batch)
        synthetic_face_recognition = (
            embeddings,
            ground_truth_classes,
            fc_weights,
            num_classes,
        )
        srfr_loss = compute_joint_loss(
            super_resolution_images,
            groud_truth_batch,
            discriminator_sr_predictions,
            discriminator_gt_predictions,
            synthetic_face_recognition,
            weight=weight,
            scale=scale,
            margin=margin,
        )
        discriminator_loss = compute_discriminator_loss(
            discriminator_sr_predictions,
            discriminator_gt_predictions,
        )
    srfr_grads = srfr_tape.gradient(srfr_loss, srfr_model.trainable_weights)
    discriminator_grads = discriminator_tape.gradient(
        discriminator_loss,
        srfr_model.trainable_weights,
    )
    return srfr_loss, srfr_grads, discriminator_loss, discriminator_grads

@tf.function
def _train_step_joint_learn(
        srfr_model,
        sr_discriminator_model,
        natural_batch,
        num_classes_natural,
        synthetic_batch,
        num_classes_synthetic,
        sr_weight: float,
        scale: float,
        margin: float,
    ):
    """Does a training step

    ### Parameters:
        srfr_model:
        sr_discriminator_model:
        natural_batch:
        num_classes_natural: Total number of classes in the natural dataset.
        synthetic_batch:
        num_classes_synthetic: Total number of classes in the synthetic dataset.
        sr_weight: Weight for the SR Loss.
        scale:
        margin:

    ### Returns:
        (srfr_loss, srfr_grads, discriminator_loss, discriminator_grads)\
 The loss value and the gradients for SRFR network, as well as the loss value\
 and the gradients for the Discriminative network.
    """
    natural_images, natural_classes = natural_batch
    synthetic_images, groud_truth_images, synthetic_classes = synthetic_batch
    with tf.GradientTape() as srfr_tape, \
        tf.GradientTape() as discriminator_tape:
        (
            synthetic_sr_images,
            synthetic_embeddings,
            synthetic_fc_weights,
            natural_sr_images,
            natural_embeddings,
            natural_fc_weights
        ) = srfr_model(synthetic_images, natural_images)
        discriminator_sr_predictions = sr_discriminator_model(synthetic_sr_images)
        discriminator_gt_predictions = sr_discriminator_model(groud_truth_images)
        synthetic_face_recognition = (
            synthetic_embeddings,
            synthetic_classes,
            synthetic_fc_weights,
            num_classes_synthetic,
        )
        natural_face_recognition = (
            natural_embeddings,
            natural_classes,
            natural_fc_weights,
            num_classes_natural,
        )
        srfr_loss = compute_joint_loss(
            synthetic_images,
            groud_truth_images,
            discriminator_sr_predictions,
            discriminator_gt_predictions,
            synthetic_face_recognition,
            natural_face_recognition,
            sr_weight,
            scale,
            margin
        )
        discriminator_loss = compute_discriminator_loss(
            discriminator_sr_predictions,
            discriminator_gt_predictions,
        )
    srfr_grads = srfr_tape.gradient(srfr_loss, srfr_model.trainable_weights)
    discriminator_grads = discriminator_tape.gradient(
        discriminator_loss,
        srfr_model.trainable_weights,
    )
    return srfr_loss, srfr_grads, discriminator_loss, discriminator_grads

@tf.function
def _train_with_natural_images(
        srfr_model,
        discriminator_model,
        batch_size,
        srfr_optimizer,
        discriminator_optimizer,
        train_loss_function,
        synthetic_dataset,
        num_classes_synthetic: int,
        natural_dataset,
        num_classes_natural: int,
        sr_weight: float = 0.1,
        scale: float = 64,
        margin: float = 0.5,
    ) -> float:
    for step, (natural_batch, synthetic_batch) in enumerate(
                zip(natural_dataset, synthetic_dataset)
        ):
        (
            srfr_loss,
            srfr_grads,
            discriminator_loss,
            discriminator_grads,
        ) = _train_step_joint_learn(
            srfr_model,
            discriminator_model,
            natural_batch,
            num_classes_natural,
            synthetic_batch,
            num_classes_synthetic,
            sr_weight,
            scale,
            margin,
        )
        srfr_optimizer.apply_gradients(
            zip(srfr_grads, srfr_model.trainable_weights)
        )
        discriminator_optimizer.apply_gradients(
            zip(discriminator_grads, discriminator_model.trainable_weights)
        )
        if step % 200 == 0:
            print(
                'SRFR Training loss (for one batch) at step {}: {}'.format(
                    step + 1,
                    float(srfr_loss)
                )
            )
            print(
                'Discriminator Training loss (for one batch) at step {}: {}'\
                    .format(step + 1, float(discriminator_loss))
            )
            print('Seen so far: {} samples'.format((step + 1) * batch_size))
    return (
        train_loss_function(srfr_loss),
        train_loss_function(discriminator_loss),
    )

@tf.function
def _train_with_synthetic_images_only(
        srfr_model,
        discriminator_model,
        batch_size,
        srfr_optimizer,
        discriminator_optimizer,
        train_loss_function,
        dataset,
        num_classes: int,
        sr_weight: float = 0.1,
        scale: float = 64,
        margin: float = 0.5,
    ) -> float:
    for step, (synthetic_images, groud_truth_images, synthetic_classes) in \
        enumerate(dataset):
        (
            srfr_loss,
            srfr_grads,
            discriminator_loss,
            discriminator_grads,
        ) = _train_step_synthetic_only(
            srfr_model,
            discriminator_model,
            synthetic_images,
            groud_truth_images,
            synthetic_classes,
            num_classes,
            sr_weight,
            scale,
            margin,
        )
        srfr_optimizer.apply_gradients(
            zip(srfr_grads, srfr_model.trainable_weights)
        )
        discriminator_optimizer.apply_gradients(
            zip(discriminator_grads, discriminator_model.trainable_weights)
        )
        if step % 200 == 0:
            print(
                'SRFR Training loss (for one batch) at step {}: {}'.format(
                    step + 1,
                    float(srfr_loss)
                )
            )
            print(
                'Discriminator Training loss (for one batch) at step {}: {}'\
                    .format(step + 1, float(discriminator_loss))
            )
            print('Seen so far: {} samples'.format((step + 1) * batch_size))
    return (
        train_loss_function(srfr_loss),
        train_loss_function(discriminator_loss),
    )

@tf.function
def train_srfr_model(
        srfr_model,
        discriminator_model,
        batch_size,
        srfr_optimizer,
        discriminator_optimizer,
        train_loss_function,
        synthetic_dataset,
        num_classes_synthetic: int,
        natural_dataset=None,
        num_classes_natural: int = None,
        sr_weight: float = 0.1,
        scale: float = 64,
        margin: float = 0.5,
    ) -> float:
    """Train the model using the given dataset, compute the loss_function and\
 apply the optimizer.

    ### Parameters:
        srfr_model: The Super Resolution Face Recognition model.
        sr_discriminator_model: The Discriminator model.
        batch_size: The Batch size.
        srfr_optimizer: Optimizer for the SRFR network.
        discriminator_optimizer: Optimizer for the Discriminator network.
        train_loss_function:
        sr_weight: Weight for the SR Loss.
        scale:
        margin:
        synthetic_dataset:
        num_classes_synthetic:
        natural_dataset:
        num_classes_natural:

    ### Returns:
        (srfr_loss, discriminator_loss) The loss value for SRFR and\
 Discriminator networks.
    """
    if natural_dataset:
        return _train_with_natural_images(
            srfr_model,
            discriminator_model,
            batch_size,
            srfr_optimizer,
            discriminator_optimizer,
            train_loss_function,
            synthetic_dataset,
            num_classes_synthetic,
            natural_dataset,
            num_classes_natural,
            sr_weight,
            scale,
            margin
        )

    return _train_with_synthetic_images_only(
        srfr_model,
        discriminator_model,
        batch_size,
        srfr_optimizer,
        discriminator_optimizer,
        train_loss_function,
        synthetic_dataset,
        num_classes_synthetic,
        sr_weight,
        scale,
        margin,
    )
