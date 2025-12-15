import sqlite3
import pandas as pd


def get_from_database(config, field):
    if config["database"]["type"] == "sqlite":
        con = sqlite3.connect(config["database"]["file_path"])
        data = pd.read_sql(f"SELECT * FROM {field}", con)
        con.close()
        return data