from datetime import datetime
import os
import pickle

loglevel = os.getenv("LOGLEVEL", "info")
raw_env = ["START_TIME=" + pickle.dumps(datetime.now())]
