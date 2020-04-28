
import json
import argparse
import tensorflow as tf
import datetime
import os
from DRBM import DRBM
from tensorflow.keras.utils import to_categorical
from mltools import LearningLog

parser = argparse.ArgumentParser("DRBM learning script.", add_help=False)
parser.add_argument("learning_config", action="store", type=str, help="path of learning configuration file.")
parser.add_argument("learning_epoch", action="store", type=int, help="numbers of epochs.")
parser.add_argument("-d", "--output_directory", action="store", type=str, default="./results/", help="directory to output parameter & log")
parser.add_argument("-s", "--filename_suffix", action="store", type=str, default=None, help="filename suffix")
args = parser.parse_args()

config = json.load(open(args.learning_config, "r"))
ll = LearningLog(config)

dtype = config["dtype"]

gen_drbm = DRBM(*config["generative-layers"], **config["generative-args"], dtype=dtype)
x_train, y_train = gen_drbm.stick_break(1000)
y_train = to_categorical(y_train, dtype=dtype)

train_ds = tf.data.Dataset.from_tensor_slices((x_train, y_train)).batch(config["minibatch-size"])
optimizer = tf.keras.optimizers.Adamax(learning_rate=0.002)

drbm = DRBM(*config["training-layers"], **config["training-args"], dtype=dtype)
drbm.fit_generative(args.learning_epoch, optimizer, train_ds, gen_drbm, ll)

now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
filename = [
    now,
    "generative",
    "h"+str(config["training-layers"][1]),
    config["training-args"]["activation"]
]
if args.filename_suffix is not None:
    filename.append(args.filename_suffix)
filename.append("%s.json")
filename = "_".join(filename)

filepath = os.path.join(args.output_directory, filename%"log")
ll.save(filepath)