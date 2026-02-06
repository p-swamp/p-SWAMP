import sqlite3
import pandas as pd
import json


def get_from_database(db_kwargs, field):
    if db_kwargs["type"] == "sqlite":
        con = sqlite3.connect(db_kwargs["file_path"],
            **{k: v for k, v in db_kwargs.items() if k not in ["type", "file_path"]})
        try:
            data = pd.read_sql(f"SELECT * FROM {field}", con)
        except pd.errors.DatabaseError:
            return
        if "index" in data.columns:
            data = data.set_index("index")
        con.close()
        return data
    
    elif db_kwargs["type"] == "file":
        with open(db_kwargs["file_path"]) as file:
            model_data = json.load(file)
        return pd.DataFrame(columns=model_data[field][0], data=model_data[field][1:])