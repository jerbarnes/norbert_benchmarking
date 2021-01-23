import numpy as np
import pandas as pd
import glob
import os
import tensorflow as tf
import transformers
from transformers import (TFBertForSequenceClassification,
                          BertTokenizer,
                          TFXLMRobertaForSequenceClassification,
                          XLMRobertaTokenizer,
                          TFBertForTokenClassification,
                          TFXLMRobertaForTokenClassification)
from tqdm.notebook import tqdm
import IPython

import sys
sys.path.append("..")
from data_preparation.data_preparation_pos import MBERT_Tokenizer, XLMR_Tokenizer, bert_convert_examples_to_tf_dataset, read_conll
import utils.utils as utils
import utils.pos_utils as pos_utils
import fine_tuning
import data_preparation.data_preparation_sentiment as data_preparation_sentiment
import utils.model_utils as model_utils

import argparse

def test(training_lang,
         test_lang,
         split="test",
         short_model_name="../checkpoints/norbert3/",
         model_name="norbert"):
    data_path = "../data/sentiment/"
    task = "sentiment"
    checkpoints_path = "checkpoints/"
    trainer = fine_tuning.Trainer(training_lang, data_path, task, short_model_name)
    # Model parameters
    max_length = 256
    eval_batch_size = 8
    learning_rate = 2e-5
    epochs = 30
    num_labels = 2
    # Model creation
    trainer.build_model(max_length, batch_size, learning_rate, epochs, num_labels, eval_batch_size=eval_batch_size)
    weights_path = "checkpoints/" + training_lang + "/"
    weights_filename = model_name + "_sentiment.hdf5"
    trainer.model.load_weights(weights_path + weights_filename)
    # Checkpoint for best model weights
    test_lang_path = data_path + test_lang
    test_data, test_dataset = data_preparation_sentiment.load_dataset(test_lang_path, trainer.tokenizer, max_length, short_model_name, dataset_name=split)
    #trainer.setup_eval(test_data, "test")
    test_dataset, test_batches = model_utils.make_batches(test_dataset, eval_batch_size, repetitions=1, shuffle=False)
    test_preds = trainer.handle_oom(trainer.model.predict,
                                    test_dataset,
                                    steps=test_batches,
                                    verbose=1)
    test_score = trainer.metric(test_preds, test_data, split) * 100
    print("{0}-{1} {2}: {3:.1f}".format(training_lang, test_lang, split, test_score))
    return test_score

def train(training_lang,
          short_model_name="../checkpoints/norbert3/",
          use_class_weights=False,
          checkpoint=None):
    data_path = "../data/sentiment/"
    task = "sentiment"
    checkpoints_path = "checkpoints/"

    trainer = fine_tuning.Trainer(training_lang, data_path, task, short_model_name, use_class_weights)

    # Model parameters
    max_length = 256
    batch_size = 8
    learning_rate = 2e-5
    epochs = 20

    # Model creation
    trainer.build_model(max_length, batch_size, learning_rate, epochs, num_labels=2, eval_batch_size=32)

    # Checkpoint for best model weights
    trainer.setup_checkpoint(checkpoints_path)

    trainer.prepare_data()

    print("Train examples:", trainer.train_data.shape[0])

    print("Example review:")
    print("{0}\t{1}".format(trainer.train_data["sentiment"][0],
                            trainer.train_data["review"][0]))
    if trainer.use_class_weights:
        trainer.calc_class_weights()
        print(trainer.class_weights)
    try:
        trainer.setup_training()
        trainer.train()
        trainer.make_definitive()
    except KeyboardInterrupt:
        pass
    return trainer

def prepare_test_data(trainer, limit=None, task="pos"):
    # Load plain data and TF dataset
    data, dataset = data_preparation_sentiment.load_dataset(
            trainer.lang_path, trainer.tokenizer, trainer.max_length,
            tagset=trainer.tagset, dataset_name="test")
    trainer.setup_eval(data, "test")
    dataset, batches = model_utils.make_batches(
            dataset, trainer.eval_batch_size, repetitions=1, shuffle=False)
    return (dataset, batches, data)



def setup_eval(data, tokenizer, label_map, max_length, dataset_name="test"):
    eval_info = {}
    eval_info[dataset_name] = {}
    eval_info[dataset_name]["all_words"] = []
    eval_info[dataset_name]["all_labels"] = []
    eval_info[dataset_name]["real_tokens"] = []
    eval_info[dataset_name]["subword_locs"] = []
    acc_lengths = 0
    #
    for i in range(len(data)):
        eval_info[dataset_name]["all_words"].extend(data[i]["tokens"]) # Full words
        eval_info[dataset_name]["all_labels"].extend([label_map[label] for label in data[i]["tags"]])
        _, _, idx_map = tokenizer.subword_tokenize(data[i]["tokens"], data[i]["tags"])
        # Examples always start at a multiple of max_length
        # Where they end depends on the number of resulting subwords
        example_start = i * max_length
        example_end = example_start + len(idx_map)
        eval_info[dataset_name]["real_tokens"].extend(np.arange(example_start, example_end, dtype=int))
        # Get subword starts and ends
        sub_ids, sub_starts, sub_lengths = np.unique(idx_map, return_counts=True, return_index=True)
        sub_starts = sub_starts[sub_lengths > 1] + acc_lengths
        sub_ends = sub_starts + sub_lengths[sub_lengths > 1]
        eval_info[dataset_name]["subword_locs"].extend(np.array([sub_starts, sub_ends]).T.tolist())
        acc_lengths += len(idx_map)
    return eval_info

def get_score_pos(preds, dataset_name, eval_info):
        filtered_preds = preds[0].argmax(axis=-1).flatten()[eval_info[dataset_name]["real_tokens"]].tolist()
        filtered_logits = preds[0].reshape(
            (preds[0].shape[0]*preds[0].shape[1], preds[0].shape[2])
        )[eval_info[dataset_name]["real_tokens"]]
        new_preds = pos_utils.reconstruct_subwords(
            eval_info[dataset_name]["subword_locs"], filtered_preds, filtered_logits
        )
        return (np.array(eval_info[dataset_name]["all_labels"]) == np.array(new_preds)).mean()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_name", default="norbert")
    parser.add_argument("--short_model_name", default="../checkpoints/norbert3/")
    parser.add_argument("--use_class_weights", action="store_true")

    args = parser.parse_args()
    print(args)

    data_dir = "../data/sentiment/"
    training_lang = "no"
    model_name = args.model_name
    short_model_name = args.short_model_name

    # Model parameters
    max_length = 256
    batch_size = 256
    num_labels = 2

    # Train models
    trainer = train(training_lang,
                    short_model_name=short_model_name)


    dev_score = test(training_lang,
                     training_lang,
                     "dev",
                     short_model_name=short_model_name,
                     model_name=model_name)

    test_score = test(training_lang,
                      training_lang,
                      "test",
                      short_model_name=short_model_name,
                      model_name=model_name)

    table = pd.DataFrame({"Train Lang": training_lang,
                          "Dev Acc": [dev_score],
                          "Test Acc": [test_score]
                          })

    print(table)
    print(table.to_latex(index=False, float_format="{0:.1f}".format))
    table.to_csv("results/{}_sentiment.csv".format(model_name))
