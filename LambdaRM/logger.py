import os
import logging


class Logger():
    """
    Log information to console and/or file
    """
    def __init__(
        self, 
        log_path=os.path.dirname(os.getcwd())+'/LambdaRM/logs/'
    ):
        self.log_path = log_path
        
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)
    
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(logging.INFO)
        self.logger.addHandler(self.console_handler)

        self.file_handler = None

    def get_logger(self， file_name):
        if self.file_handler is not None:
            self.logger.removeHandler(self.file_handler)

        log_name = self.log_path + "{}.txt".format(file_name)
        self.file_handler = logging.FileHandler(log_name, mode='w')
        self.file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.file_handler)

        return self.logger
    
    def shutdown_logger(self):
        logging.shutdown()
        
        