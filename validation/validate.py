import logging

import numpy as np
import tensorflow as tf
from scipy import interpolate
from scipy.optimize import brentq
from sklearn import metrics
from sklearn.preprocessing import normalize

from validation.lfw_helper import evaluate

LOGGER = logging.getLogger(__name__)


def _predict(images_batch, images_aug_batch, model):
    _, embeddings = model(images_batch, training=False)
    _, embeddings_augmented = model(images_aug_batch, training=False)
    embeddings = embeddings + embeddings_augmented

    if tf.math.reduce_all(tf.math.equal(embeddings, 0)):
        # If the array is full of 0's, the following calcs that will use it
        # will return NaNs or 0, and at some point the validation algorithm will
        # crash at some division because of the NaNs or the 0's.
        # To not fall on this path, we will insert a value very close to 0
        # instead.
        embeddings = tf.convert_to_tensor(
            np.full_like(embeddings.numpy(), 10e-8),
            dtype=tf.float32,
        )

    return normalize(embeddings.numpy(), axis=1)


def _predict_on_batch(strategy, model, dataset):
    embeddings = np.array([])
    for images_batch, images_aug_batch in dataset:
        embedding_per_replica = strategy.run(
            _predict, args=(images_batch, images_aug_batch, model)
        )
        # `embedding_per_replica` is a tuple of EagerTensors, and each tensor
        # has a shape of [batch_size, 512], so we need to get each EagerTensor
        # that is in the tuple, and get each single embedding array that is in
        # the outputted array, appending each of them to the embeddings list.
        for tensor in embedding_per_replica.values:

            # Some tensors have NaNs among the values, so we check them and add
            # 0s in its places
            if np.isnan(np.sum(tensor)):
                tensor = np.nan_to_num(tensor)

            if embeddings.size == 0:
                embeddings = tensor
            else:
                try:
                    embeddings = np.concatenate((embeddings, tensor), axis=0)

                # Sometimes the outputted embedding array isn't in the shape of
                # (batch_size, embedding_size), so we need to expand_dims
                # to transform this array from (embedding_size, ) to
                # (1, embedding_size) before concatenatting with `embeddings`
                except ValueError:
                    new_embeddings = np.expand_dims(tensor, axis=0)
                    embeddings = np.concatenate((embeddings, new_embeddings), axis=0)

    return embeddings


def _get_embeddings(
    strategy,
    model,
    left_pairs,
    right_pairs,
    is_same_list,
):
    left_pairs = _predict_on_batch(strategy, model, left_pairs)
    right_pairs = _predict_on_batch(strategy, model, right_pairs)

    embeddings = []
    for left, right in zip(left_pairs, right_pairs):
        embeddings.append(left)
        embeddings.append(right)

    return np.array(embeddings), is_same_list


def validate_model_on_lfw(
    strategy,
    model,
    left_pairs,
    right_pairs,
    is_same_list,
) -> float:
    """Validates the given model on the Labeled Faces in the Wild dataset.

    ### Parameters
        model: The model to be tested.
        dataset: The Labeled Faces in the Wild dataset, loaded from load_lfw\
 function.
        pairs: List of LFW pairs, loaded from load_lfw_pairs function.

    ### Returns
        (accuracy_mean, accuracy_std, validation_rate, validation_std, far,\
 auc, eer) - Accuracy Mean, Accuracy Standard Deviation, Validation Rate,\
 Validation Standard Deviation, FAR, Area Under Curve (AUC) and Equal Error\
 Rate (EER).
    """
    embeddings, is_same_list = _get_embeddings(
        strategy,
        model,
        left_pairs,
        right_pairs,
        is_same_list,
    )

    tpr, fpr, accuracy, val, val_std, far = evaluate(embeddings, is_same_list)
    auc = metrics.auc(fpr, tpr)
    eer = brentq(lambda x: 1.0 - x - interpolate.interp1d(fpr, tpr)(x), 0.0, 1.0)
    return np.mean(accuracy), np.std(accuracy), val, val_std, far, auc, eer


def get_images(strategy, model, dataset):
    for images_batch, _ in dataset:
        super_resolution_images = strategy.run(
            _get_super_resolution_images, args=(images_batch, model)
        )
        return images_batch, super_resolution_images


def _get_super_resolution_images(image_batch, model):
    super_resolution_images, _ = model(image_batch, training=False)
    return super_resolution_images
