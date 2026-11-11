#!/bin/sh
cd /DATA/AppData/plexpoint-files-office
systemctl restart filepoint-storage.service
python3 -B -m unittest discover -s foldericons -p 'test_*.py' > foldericons/storage-tests.log 2>&1
python3 -B foldericons/storage_host_check.py
