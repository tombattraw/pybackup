#!/usr/bin/env python3

import os, hashlib, pathlib, argparse, yaml, sys, pwd, subprocess, datetime, shutil, gzip

CONFIG_LOCATION = pathlib.Path('/etc/pybackup')
CONFIG_FILE = CONFIG_LOCATION / 'config.yaml'
SCRIPT_LOCATION = pathlib.Path('/bin/pybackup.py')
BACKUP_LOCATION = pathlib.Path('/opt/backups')
SERVICE_PATH = '/etc/systemd/system/pybackup.service'
ROOT = os.geteuid() == 0
UID = os.geteuid()
TIME = datetime.datetime.now()
TIME_STR = TIME.strftime('%Y-%m-%d_%H:%M')
LASTRUN_FILE = BACKUP_LOCATION / 'lastrun.txt'

with open(LASTRUN_FILE, 'r') as f:
    LASTRUN = datetime.datetime.fromtimestamp(int(f.read()))

# list should give list of backed-up directories and timestamps; restore should take directory and timestamp to 
# check file perms - don't show other users' files to nonroot users
# hardlink intervals created at same time
# to implement: scp, rsync, smb 

# TO BACKUP:
# rotate if needed, but don't move the first: copy it, then perform an incremental update on it.


class Destination:
    def __init__(self, source_path, dest_path, config):
        self.source_path = source_path
        self.dest_path = dest_path
        self.method = config['method']['type']
        self.intervals = config['intervals']

        # Check to see if backup is needed for each configured interval
        self.intervalDict = {}
        for interval in self.intervals.keys():
            if (TIME - datetime.timedelta(**{interval:1})) > LASTRUN:
                self.intervalDict[interval] = self.intervals[interval]

    def backup(self):
        for index, interval in enumerate(self.intervalDict.keys()):
            interval_backup_location = BACKUP_LOCATION / interval
            interval_backup_dir = interval_backup_location / TIME_STR

            # If an earlier interval was created, just link to it
            if index != 0 and (BACKUP_LOCATION / list(self.intervalDict.keys())[0]).exists():
                (BACKUP_LOCATION / list(self.intervalDict.keys())[0]).symlink_to(interval_backup_dir)
                continue

            if not interval_backup_location.exists(): interval_backup_location.mkdir(mode=0o700)
            interval_backup_dir.mkdir(mode=0o700)

            
            


            



class Source:
    def __init__(self, path, destinations):
        self.path = path
        self.destinations = [Destination(self.path, x, destinations[x]) for x in destinations.keys()]

    def backup(self, destinations=None):
        if not destinations:
            for destination in self.destinations:
                destination.backup()




def parseArgs():
    parser = argparse.ArgumentParser(prog='pybackup.py')
    parser.add_argument('action', choices=['install', 'uninstall','backup', 'cleanup', 'list', 'restore', 'daemon'])
        # add subparsers for specific directories to back up?
    return parser.parse_args()


def install():
    if not ROOT:
        print('Installation must be done with root permissions')
        sys.exit()

    try: CONFIG_LOCATION.mkdir(mode=0o755)
    except FileExistsError:
        print(f'[!] It appears that this was already installed. Run "{sys.argv[0]} uninstall" to ready for installation')
        sys.exit()

    BACKUP_LOCATION.mkdir(mode=0o700)
    for interval in ['minutes', 'hours', 'days', 'weeks', 'months', 'years']:
        (BACKUP_LOCATION / interval).mkdir(mode=0o700)

    config_str = f'source:\n  - destination:\n    - method:\n      - type: # scp, smb, cp\n      - key:\n      - username:\n      - password:\n    - intervals:\n      - minutes: 0\n      hours: 8\n      days: 5\n      weeks: 4\n      - months: 3\n      - years: 0'

    with open(CONFIG_FILE, 'w') as f:
        f.write(config_str)
    CONFIG_LOCATION.chmod(mode=0o644)

    SCRIPT_LOCATION.write_bytes(pathlib.Path(sys.argv[0]).read_bytes())
    SCRIPT_LOCATION.chmod(mode=0o755)

    with open(LASTRUN_FILE, 'w') as f:
        f.write('0')

    with open(SERVICE_PATH, 'w') as f:
        f.write(f'''\n[Unit]\nDescription=Pybackup\nAfter=multi-user.target\n\n[Service]\nExecStart="{SCRIPT_LOCATION} daemon"\n\n[Install]\nWantedBy=multi-user.target''')
    SERVICE_PATH.chmod(mode=0o644)

    pathlib.Path('/etc/systemd/system/multi-user.target.wants/pybackup.service').symlink_to(SERVICE_PATH)

    subprocess.run('systemctl daemon-reload')

    print('Installation complete')


def uninstall():
    if not ROOT:
        print('Uninstallation must be done with root permissions')
        sys.exit()

    for file in [CONFIG_FILE, CONFIG_LOCATION, SCRIPT_LOCATION, SERVICE_PATH, pathlib.Path('/etc/systemd/system/multi-user.target.wants/pybackup.service')]:
        file.unlink()

    remove = input('Delete backups? [y/N] ')
    if remove.lower().strip() == 'y':
        shutil.rmtree(BACKUP_LOCATION)

    CONFIG_LOCATION.rmdir()

    print('Uninstallation complete')


def backup():
    with open(CONFIG_FILE, 'r') as f:
        config = yaml.safe_load(f)

    # Backdate the timestamp a touch to ensure that marginal files aren't missed
    with open(LASTRUN_FILE, 'w') as f:
        f.write(int(TIME.timestamp()) - 10)

    sources = [Source(x, config[x]) for x in config.keys()]
    for source in sources: source.backup()



def walk(): do_stuff
def rotate(): do_stuff

'''
source (/home/user/):
  destination (/archive/backup):
    - method: # literal
      - type: (scp, rsync, smb, cp)
      - key: /home/user/.ssh/id_rsa
      - username: user
      - password: password
    - intervals: # literal
      - minutes: 0
      - hours: 6
      - days: 3
      - weeks: 4
      - months: 6
      - years: 0
'''






if __name__ == "__main__":
    args = parseArgs()

    match args.action:
        case 'install': install()
        case 'uninstall': uninstall()
        case 'backup': backup()
        case 'cleanup': cleanup()
        case 'list': lst()
        case 'daemon': daemon()
