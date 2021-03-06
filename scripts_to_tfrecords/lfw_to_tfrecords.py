import logging
from pathlib import Path

import cv2
import tensorflow as tf
from utils.timing import TimingLogger
from utils.input_data import InputData, parseConfigsFile

logging.basicConfig(
    filename='lfw_to_tfrecords.txt',
    level=logging.INFO
)
LOGGER = logging.getLogger(__name__)
timing = TimingLogger()
timing.start()

LOGGER.info('--- Setting Functions ---')
shape = tuple(parseConfigsFile(['preprocess'])['image_shape_low_resolution'][:2])


def _reduce_resolution(high_resolution_image):
    low_resolution_image = cv2.cvtColor(
        cv2.resize(high_resolution_image, shape, interpolation=cv2.INTER_CUBIC),
        cv2.COLOR_BGR2RGB)
    return tf.image.encode_png(low_resolution_image)


def _bytes_feature(value):
    if isinstance(value, type(tf.constant(0))):
        value = value.numpy() # BytesList won't unpack a string from an EagerTensor.
    try:
        value = value.encode('utf-8')
    except Exception:
        pass
    return tf.train.Feature(bytes_list=tf.train.BytesList(value=[value]))


def _int64_feature(value):
    return tf.train.Feature(int64_list=tf.train.Int64List(value=[value]))


def image_example(image_string_low_resolution, _class_id, _sample_id):
    feature = {
        'class_id': _bytes_feature(_class_id),
        'sample_id': _bytes_feature(_sample_id),
        'image_low_resolution': _bytes_feature(image_string_low_resolution),
    }
    return tf.train.Example(features=tf.train.Features(feature=feature))


def preprocess_image(image_path):
    class_id, sample_id = InputData.split_path(str(image_path))
    high_resolution_image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    low_resolution = _reduce_resolution(high_resolution_image)
    return image_example(
        low_resolution,
        class_id,
        sample_id
    )


data_dir = Path('/mnt/hdd_raid/datasets/LFW_LR/Images/train')
data_dir = list(data_dir.glob('*/*.jpg'))
partial = 1
total = len(data_dir)
PATH = '/mnt/hdd_raid/datasets/LFW_LR/TFRecords/Raw_Low_Resolution.tfrecords'
LOGGER.info(' Started Recording')

with tf.io.TFRecordWriter(PATH) as writer:
    for image in data_dir:
        LOGGER.info(f' Image {partial}/{total}')
        tf_example = preprocess_image(image)
        writer.write(tf_example.SerializeToString())
        partial += 1
