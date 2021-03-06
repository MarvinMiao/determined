import argparse
import pathlib
from typing import Callable, Dict, Tuple

import tensorflow as tf

from determined import estimator
from determined.experimental import estimator as estimator_experimental
from tests.experiment import utils


def xor_input_fn(
    context: estimator.EstimatorNativeContext, batch_size: int, shuffle: bool = False
) -> Callable[[], Tuple[tf.Tensor, tf.Tensor]]:
    def _input_fn() -> Tuple[tf.Tensor, tf.Tensor]:
        data, labels = utils.xor_data()
        dataset = tf.data.Dataset.from_tensor_slices((data, labels))
        dataset = context.wrap_dataset(dataset)
        if shuffle:
            dataset = dataset.shuffle(1000)

        def map_dataset(x, y):
            return {"input": x}, y

        dataset = dataset.batch(batch_size)
        dataset = dataset.map(map_dataset)

        return dataset

    return _input_fn


def build_estimator(context: estimator.EstimatorNativeContext) -> tf.estimator.Estimator:
    optimizer = context.get_hparam("optimizer")
    learning_rate = context.get_hparam("learning_rate")
    hidden_size = context.get_hparam("hidden_size")

    _input = tf.feature_column.numeric_column("input", shape=(2,), dtype=tf.int32)

    if optimizer == "adam":
        optimizer = tf.compat.v1.train.AdamOptimizer(learning_rate=learning_rate)
    elif optimizer == "sgd":
        optimizer = tf.compat.v1.train.GradientDescentOptimizer(learning_rate=learning_rate)
    else:
        raise NotImplementedError()
    optimizer = context.wrap_optimizer(optimizer)

    return tf.compat.v1.estimator.DNNClassifier(
        feature_columns=[_input],
        hidden_units=[hidden_size],
        activation_fn=tf.nn.sigmoid,
        config=tf.estimator.RunConfig(
            session_config=tf.compat.v1.ConfigProto(
                intra_op_parallelism_threads=1, inter_op_parallelism_threads=1
            )
        ),
        optimizer=optimizer,
    )


def build_serving_input_receiver_fns() -> Dict[str, estimator.ServingInputReceiverFn]:
    _input = tf.feature_column.numeric_column("input", shape=(2,), dtype=tf.int64)
    return {
        "inference": tf.estimator.export.build_parsing_serving_input_receiver_fn(
            tf.feature_column.make_parse_example_spec([_input])
        )
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()

    config = {
        "hyperparameters": {
            "hidden_size": 2,
            "learning_rate": 0.1,
            "global_batch_size": 4,
            "optimizer": "sgd",
            "shuffle": False,
        }
    }

    context = estimator_experimental.init(
        config=config, local=args.local, test=args.test, context_dir=str(pathlib.Path.cwd())
    )

    batch_size = context.get_per_slot_batch_size()
    shuffle = context.get_hparam("shuffle")
    context.serving_input_receiver_fns = build_serving_input_receiver_fns()
    context.train_and_evaluate(
        build_estimator(context),
        tf.estimator.TrainSpec(
            xor_input_fn(context=context, batch_size=batch_size, shuffle=shuffle), max_steps=1
        ),
        tf.estimator.EvalSpec(xor_input_fn(context=context, batch_size=batch_size, shuffle=False)),
    )
