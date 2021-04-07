import numpy as np
import pandas as pd
from sklearn.metrics import mutual_info_score
from colorama import Fore, Style
from time import perf_counter, sleep, strftime
import csv
import threading

from CASAS_committee_predict import CASASCommitteePredict
from ARAS_committee_predict import ARASCommitteePredict
from query_select import QuerySelect
from dialogue_manager import DialogueManager
from ARAS_annotator import ARASAnnotator
from CASAS_annotator import CASASAnnotator
from CASAS_AL_tools import CASASALTools
from label_linker import LabelLinker
from log import Log

QUERY_LIMIT = 4000
QUERY_RETRAIN = 25

class QueryProcessControl(object):
    def __init__(self):
        self.id = 'query_process_control'

        self.logger = Log(self.id)
        self.logger.startup_msg()

        # * * * CONFIGURATION AREA * * * 

        # set to True for real-time mode (1 second/sample)
        self.real_time = False

        # set to True for automatic labelling
        self.oracle = False

        # set to True for automated re-training
        self.auto_al = True

        # set a limit on the number of predictions (for debug)
        self.max_predictions = 0

        # enable/disable debug mode (more verbose)
        self.debug = False

        # select the dataset
        self.dataset = "CASAS"

        # * * * * * * * * * * * * * * *

        self.sample_counter = 0
        self.num_queries = 0
        self.num_queries_at_last_retrain = 0

        if self.dataset == "CASAS":
            self.al_tools = CASASALTools()
            if self.auto_al:
                self.al_tools.init()
            self.committee_predict = CASASCommitteePredict(self.debug)
            self.annotator = CASASAnnotator(self.debug, self.dataset, self.committee_predict)
        elif self.dataset == "ARAS":
            self.committee_predict = ARASCommitteePredict(self.debug)
            self.annotator = ARASAnnotator(self.debug, self.dataset, self.committee_predict)
        else:
            self.logger.log_warn('Invalid dataset configuration.')

        self.query_select = QuerySelect(self.debug)
        self.label_linker = LabelLinker(self.dataset)
        self.dialogue_manager = DialogueManager(self.annotator, self.label_linker)

        self.create_csv()

        self.logger.log_great('Ready.')

    def run(self):
        self.committee_predict.reset_counter()
        self.max_predictions = self.committee_predict.get_max_predictions()

        for i in range(0, self.max_predictions):
            if i > 0 and self.real_time:
                start_time = perf_counter()

            committee_vote_1, committee_vote_2, committee_vote_3, true = self.committee_predict.next_prediction()
            current_sample = self.committee_predict.get_current_sample()
            self.annotator.add_sample(current_sample)
            max_disagreement, query_decision, disagreement_type = self.query_select.insert_sample(committee_vote_1, committee_vote_2, committee_vote_3, true)
            committee_vote_1, committee_vote_2, committee_vote_3, true = self.inverse_transform_labels(committee_vote_1, committee_vote_2, committee_vote_3, true)
            votes = [committee_vote_1, committee_vote_2, committee_vote_3]

            self.csv_log(committee_vote_1, committee_vote_2, committee_vote_3, true, max_disagreement, query_decision)

            if query_decision:
                self.num_queries = self.num_queries + 1
                self.annotator.lock_buffer()
                if self.real_time:
                    threading.Thread(target=lambda: self.dialogue_manager.start_query(votes)).start()
                else:
                    if self.oracle:
                        self.annotator.annotate_buffer(true)
                    else:   
                        self.dialogue_manager.start_query(votes)

            # if query_decision:
            #     self.csv_log(committee_vote_1, committee_vote_2, committee_vote_3, true, disagreement_type, query_decision)

            if i > 0 and self.real_time:
                end_time = perf_counter()
                time_taken = end_time - start_time
                delay_time = 1.0 - time_taken

                if delay_time >= 0.0:
                    print('Prediction time was:', time_taken, ', sleeping for:', delay_time, 'seconds')
                    sleep(delay_time)
                else:
                    self.logger.log_warn('Predict/analyse cycle took longer than 1 second! System is not keeping up with real-time.')

            self.sample_counter = self.sample_counter + 1
            print('progress:', self.sample_counter, 'of', self.max_predictions)

            if self.num_queries == QUERY_LIMIT:
                self.logger.log_warn('Query limit reached. Terminating.')
                break
            
            if self.auto_al:
                annotations_filename = self.annotator.get_annotation_filename()
                if (self.num_queries % QUERY_RETRAIN == 0) and (self.num_queries > 0) and (self.num_queries_at_last_retrain != self.num_queries):
                    self.al_tools.update(annotations_filename)
                    self.num_queries_at_last_retrain = self.num_queries

    # Logging

    def create_csv(self):
        date_time = strftime("%Y%m%d-%H%M%S")
        self.csv_filename = 'logs/output_' + date_time + '.csv'

        msg = 'The logfile for this session is: ' + self.csv_filename
        self.logger.log(msg)

        with open(self.csv_filename, 'w', newline='') as fd:
            writer = csv.writer(fd)
            writer.writerow(["Sample Count", "Learner 1", "Learner 2", "Learner 3", "Truth", "Max Disagreement", "Query Decision"])

    def csv_log(self, committee_vote_1, committee_vote_2, committee_vote_3, true, disagreement_type, query_decision):
        # committee_vote_1, committee_vote_2, committee_vote_3, true = self.inverse_transform_labels(committee_vote_1, committee_vote_2, committee_vote_3, true)
        log_row = [self.sample_counter, committee_vote_1, committee_vote_2, committee_vote_3, true, disagreement_type, query_decision]
        with open(self.csv_filename, 'a') as fd:
            writer = csv.writer(fd)
            writer.writerow(log_row)

    # Utilities

    def inverse_transform_labels(self, committee_vote_1, committee_vote_2, committee_vote_3, true):
        committee_vote_1 = np.argmax(committee_vote_1)
        committee_vote_2 = np.argmax(committee_vote_2)
        committee_vote_3 = np.argmax(committee_vote_3)

        committee_vote_1 = self.committee_predict.get_label(committee_vote_1)
        committee_vote_2 = self.committee_predict.get_label(committee_vote_2)
        committee_vote_3 = self.committee_predict.get_label(committee_vote_3)
        true = self.committee_predict.get_label(true)

        return committee_vote_1, committee_vote_2, committee_vote_3, true

if __name__ == '__main__':
    qpc = QueryProcessControl()
    qpc.run()