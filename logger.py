import logging
import os
from datetime import datetime

class Logger:
    def __init__(self, name):
        # 创建logs文件夹
        if not os.path.exists('logs'):
            os.makedirs('logs')
            
        # 设置日志文件名（包含日期）
        log_file = f'logs/{name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        
        # 配置日志格式
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        self.logger = logging.getLogger(name)
    
    def info(self, message):
        self.logger.info(message)
    
    def error(self, message, exc_info=True):
        self.logger.error(message, exc_info=exc_info)
    
    def warning(self, message):
        self.logger.warning(message) 