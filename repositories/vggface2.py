from typing import Tuple, Union

import tensorflow as tf
from utils.input_data import parseConfigsFile

from repositories.repository import BaseRepository

AUTOTUNE = tf.data.experimental.AUTOTUNE


class VggFace2(BaseRepository):
    def __init__(
        self,
        remove_overlaps: bool = True,
        sample_ids: bool = False,
    ):
        super().__init__()
        self._remove_overlaps = remove_overlaps
        self._sample_ids = sample_ids
        if self._sample_ids:
            self._dataset_shape = "iics"
        else:
            self._dataset_shape = "iic"

        if self._remove_overlaps:
            self._number_of_train_classes = 8069
            self._number_of_test_classes = 460
        else:
            self._number_of_train_classes = 8631
            self._number_of_test_classes = 500

        self._serialized_features = {
            "class_id": tf.io.FixedLenFeature([], tf.string),
            "sample_id": tf.io.FixedLenFeature([], tf.string),
            "image_low_resolution": tf.io.FixedLenFeature([], tf.string),
            "image_high_resolution": tf.io.FixedLenFeature([], tf.string),
        }
        self._dataset_settings = parseConfigsFile(["dataset"])["vggface2_lr"]
        self._dataset_paths = {
            "train": self._dataset_settings["train_path"],
            "test": self._dataset_settings["test_path"],
            "both": [
                self._dataset_settings["train_path"],
                self._dataset_settings["test_path"],
            ],
        }

        self._logger = super().get_logger()
        self._class_pairs = super()._get_class_pairs("VGGFace2_LR", "concatenated")
        super().set_class_pairs(self._class_pairs)
        self._dataset = None

        self._get_concatenated_dataset()
        self._dataset_size = self.get_dataset_size(self._dataset)

    def _get_concatenated_dataset(self):
        self._logger.info(f" Loading VGGFace2_LR in concatenated mode.")

        dataset = super().load_dataset(
            "VGGFace2_LR",
            self._dataset_paths["both"],
            self._decoding_function,
            "concatenated",
            remove_overlaps=self._remove_overlaps,
            sample_ids=self._sample_ids,
        )

        self._dataset = self._convert_tfrecords(dataset)

    def get_train_dataset(self):
        self._logger.info(f" Loading VGGFace2_LR in train mode.")

        return self._dataset.take(int(0.7 * self._dataset_size))

    def get_test_dataset(self):
        self._logger.info(f" Loading VGGFace2_LR in test mode.")

        return self._dataset.skip(int(0.7 * self._dataset_size))

    def get_concatenated_datasets(self):
        self._logger.info(f" Loading VGGFace2_LR in concatenated mode.")

        dataset = super().load_dataset(
            "VGGFace2_LR",
            self._dataset_paths["both"],
            self._decoding_function,
            "concatenated",
            remove_overlaps=self._remove_overlaps,
            sample_ids=self._sample_ids,
        )

        return self._convert_tfrecords(dataset)

    def _convert_tfrecords(self, dataset):
        return dataset.map(
            super()._convert_class_ids_with_sample_id,
            num_parallel_calls=AUTOTUNE,
        )

    def _get_number_of_classes(self):
        classes = set()
        for _, _, class_id in self._dataset:
            classes.add(class_id.numpy())

        num_classes = len(classes)
        print(num_classes)
        return num_classes

    def get_number_of_classes(self) -> Union[int, Tuple[int]]:
        # return 272
        # return 27
        # if self._mode == "train":
        #    return self._number_of_train_classes
        # if self._mode == "test":
        #    return self._number_of_test_classes
        # if self._mode == "concatenated":
        #    return self._number_of_train_classes + self._number_of_test_classes
        # return self._number_of_train_classes, self._number_of_test_classes
        return 9294

    def get_dataset_size(self, dataset):
        return super()._get_dataset_size(dataset)

    def get_dataset_shape(self):
        return self._dataset_shape

    @tf.function
    def _decoding_function(self, serialized_example):
        deserialized_example = tf.io.parse_single_example(
            serialized_example,
            self._serialized_features,
        )
        image_lr = super()._decode_raw_image(
            deserialized_example["image_low_resolution"]
        )
        # image_lr.set_shape(image_shape)
        image_lr = tf.reshape(
            image_lr,
            tf.stack(
                [*super().get_preprocess_settings()["image_shape_low_resolution"]]
            ),
        )
        image_hr = super()._decode_raw_image(
            deserialized_example["image_high_resolution"]
        )
        image_hr = tf.reshape(
            image_hr,
            tf.stack(
                [*super().get_preprocess_settings()["image_shape_high_resolution"]]
            ),
        )

        class_id = super()._decode_string(deserialized_example["class_id"])
        if self._sample_ids:
            self._dataset_shape = "iics"
            sample_id = self._decode_string(deserialized_example["sample_id"])
            return image_lr, image_hr, class_id, sample_id

        self._dataset_shape = "iic"
        return image_lr, image_hr, class_id

    def augment_dataset(self, dataset):
        self._logger.info(" Augmenting VggFace2_LR dataset.")
        return super().augment_dataset(dataset, self.get_dataset_shape())

    def normalize_dataset(self, dataset):
        self._logger.info(" Normalizing VggFace2_LR dataset.")
        return dataset.map(
            lambda image_lr, image_hr, class_id: (
                self.normalize_image(image_lr),
                self.normalize_image(image_hr),
                class_id,
            ),
            num_parallel_calls=AUTOTUNE,
        )
