#!/bin/bash
cd /root/music
pip install -r requirements.txt
sudo apt update && sudo apt install -y ffmpeg
python bot.py