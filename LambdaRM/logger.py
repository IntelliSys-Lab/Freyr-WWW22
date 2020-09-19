import os
import logging


class Logger():
    """
    Log information to console and/or file
    """
    def __init__(
        self, 
        file_name, 
        log_path=os.path.dirname(os.getcwd())+'/serverless/logs/'
    ):
        self.file_name = file_name
        self.log_path = log_path
        
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)
    
        log_name = self.log_path + "{}.txt".format(self.file_name)
    
        self.console_handler = logging.StreamHandler()
        self.console_handler.setLevel(logging.INFO)
        self.file_handler = logging.FileHandler(log_name, mode='w')
        self.file_handler.setLevel(logging.DEBUG)
        
        self.logger.addHandler(self.file_handler)
        self.logger.addHandler(self.console_handler)

    def get_logger(self):
        return self.logger
    
    def shutdown_logger(self):
        handler_list = [self.console_handler, self.file_handler]
#         logging.shutdown(handler_list)
        logging.shutdown()
        
        