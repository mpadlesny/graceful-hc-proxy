from datetime import datetime
import pickle

raw_env = ["START_TIME=" + pickle.dumps(datetime.now())]
