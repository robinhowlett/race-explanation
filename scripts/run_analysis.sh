#!/bin/bash
cd /home/robin/dev/race-explanation
source .venv/bin/activate

echo "=== Starting analysis at $(date) ===" > /home/robin/race_analysis.log

echo "=== Building lookup tables ===" >> /home/robin/race_analysis.log
python -u scripts/build_race_lookup_tables.py >> /home/robin/race_analysis.log 2>&1

echo "" >> /home/robin/race_analysis.log
echo "=== Position prediction validation (500 races) ===" >> /home/robin/race_analysis.log
python -u scripts/validate_position_prediction.py >> /home/robin/race_analysis.log 2>&1

echo "" >> /home/robin/race_analysis.log
echo "=== In-running model validation (300 races) ===" >> /home/robin/race_analysis.log
python -u scripts/validate_in_running.py >> /home/robin/race_analysis.log 2>&1

echo "" >> /home/robin/race_analysis.log
echo "=== Race explanation validation (200 races) ===" >> /home/robin/race_analysis.log
python -u scripts/validate_race_explanation.py >> /home/robin/race_analysis.log 2>&1

echo "" >> /home/robin/race_analysis.log
echo "=== Done at $(date) ===" >> /home/robin/race_analysis.log
echo "DONE" >> /home/robin/race_analysis.log
