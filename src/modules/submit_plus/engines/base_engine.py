# base_engine.py

class BaseEngine:

    def run(self, data: dict):
        raise NotImplementedError("Each engine must implement the run() method")