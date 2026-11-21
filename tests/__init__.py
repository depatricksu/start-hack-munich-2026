import os  # noqa
os.environ["HUMAN_LEARN"] = "0"   # llm/human.py: tests never write the live learning file
os.environ["BID_ALWAYS"] = "0"    # tests verify the default fast-path; the runner's .env enables BID_ALWAYS separately
