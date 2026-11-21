import os, tempfile  # noqa
os.environ["HUMAN_LEARN"] = "0"   # llm/human.py: tests never write the live learning file
os.environ["BID_ALWAYS"] = "0"    # tests verify the default fast-path; the runner's .env enables BID_ALWAYS separately
# Tests never read the runner's live tariff updates. pricing/price.py reads data/tariff_overrides.json by default, and
# that file changes the moment a real airline sends new rates: on 21 Nov 23:03 Cobalt Skylift's monthly update made
# five tests expect old prices and core.restart refused every new version on the runner.
os.environ["TARIFF_OVERRIDES"] = os.path.join(tempfile.mkdtemp(), "tariff_overrides.json")
