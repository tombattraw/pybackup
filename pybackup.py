#!/usr/bin/env python3

import os, hashlib, pathlib, argparse, yaml, sys, pwd, subprocess, datetime, shutil, gzip, calendar
from collections import OrderedDict

CONFIG_LOCATION = pathlib.Path('/etc/pybackup')
CONFIG_FILE = CONFIG_LOCATION / 'config.yaml'
SCRIPT_LOCATION = pathlib.Path('/bin/pybackup.py')
BACKUP_LOCATION = pathlib.Path('/opt/backups')
SERVICE_PATH = pathlib.Path('/etc/systemd/system/pybackup.service')
ROOT = os.geteuid() == 0
UID = os.geteuid()
TIME = datetime.datetime.now().replace(second=0, microsecond=0)
TIME_STR = TIME.strftime('%Y-%m-%d_%H:%M')
LASTRUN_FILE = BACKUP_LOCATION / 'lastrun.txt'

with open(LASTRUN_FILE, 'r') as f:
    LASTRUN = datetime.datetime.fromtimestamp(int(f.read()))

# list should give list of backed-up directories and timestamps; restore should take directory and timestamp to 
# check file perms - don't show other users' files to nonroot users
# to implement: scp, rsync, smb 


class Interval:
    # Takes a cron-style string "*/5 - 1,3,7 - 30 - 10-12 - *"
    # Intended use is to verify validity when instantiated, then check if the next backup should be started using "<object>.shouldBackup()"

    def __init__(self, cron_string):
        self._intervalDict = OrderedDict.fromkeys(self.FIELD_NAMES)

        self._validRanges = {
            'minute': range(0, 60),
            'hour': range(0, 24),
            'dayOfMonth': range(1, calendar.monthrange(TIME.year, TIME.month)[1]+1),
            'month': range(1, 13),
            'dayOfWeek': range(0, 8) # 0 and 7 are both Sunday
        }

        self._parse_cron_string(cron_string)


    def _parse_cron_string(self, cron_string):
        # Takes a cron-style string
        # Raises ValueErrors if the number of fields is incorrect
        # Returns lists of valid ints for each interval

        FIELD_NAMES = ['minute', 'hour', 'dayOfMonth', 'month', 'dayOfWeek']

        fields = cron_string.strip().split()
        if len(fields) != 5:
            raise ValueError("Cron string must have exactly 5 fields")

        for name, value in zip(FIELD_NAMES, fields):
            self._intervalDict[name] = self._parseInterval(name, value)


    def _parseInterval(self, intervalType, intervalString):
        # Takes a cron-style string for a given interval: "*/5", "1,3,7", or "2-6"
        # Returns a list of valid values
        # Raises ValueErrors if given values are out of range

        validMin = self._validRanges[intervalType][0]
        validMax = self._validRanges[intervalType][-1]
        validRange = self._validRanges[intervalType]

        # "/" used to set step value
        values = []
        if '/' in intervalString:
            if intervalString.count('/') > 1:
                raise ValueError('Can only have one "/" in interval')
            intervalString, step = intervalString.split('/')
            step = int(step)
        else:
            step = 1
        
        # "," used to denote lists of values
        # unparsedValues is a list of strings, parsedValues is a list of integers generated from the strings
        unparsedValues = intervalString.split(',')
        parsedValues = []

        for uV in unparsedValues:
            # "-" used to denote ranges
            if '-' in uV:
                if uV.count('-') > 1:
                    raise ValueError('Can only have one "-" in range')
                
                beginning, end = uV.split('-')
                if int(beginning) < validMin:
                    raise ValueError(f'{beginning} too low for the {intervalType} range')
                if int(end) < int(beginning):
                    raise ValueError(f'{end} is greater than {beginning} for the {intervalType} range')

                # Silently correcting to avoid usually-valid date overruns like a 30 overflowing Feb 28
                end = int(end) if int(end) in validRange else validMax
                parsedValues.extend(range(int(beginning), int(end)+1, step))

            # "*" used to mean every valid value
            elif uV == '*':
                parsedValues.extend(range(validMin, validMax+1, step))

            else:
                if int(uV) not in validRange:
                    raise ValueError(f'{uV} out of range for {intervalType}')
                parsedValues.append(int(uV))
        
        return sorted(list(set(parsedValues)))
                

    def shouldBackup(self):
        # Accepts no input
        # Returns True if the source has had a backup interval elapse since the script was last run, else False.
        currentDate = LASTRUN.date()
        endDate = TIME.date()

        while currentDate <= endDate:
            # Only check days that match the cron constraints
            candidateDay = datetime.datetime.combine(currentDate, datetime.datetime.min.time())
            
            if (candidateDay.month in self._intervalDict['month'] and
                candidateDay.day in self._intervalDict['dayOfMonth'] and
                (candidateDay.weekday() in self._intervalDict['dayOfWeek'] or 
                (7 in self._intervalDict['dayOfWeek'] and candidateDay.weekday() == 6))):

                # Now check each valid hour/minute on this day
                for hour in self._intervalDict['hour']:
                    for minute in self._intervalDict['minute']:
                        try:
                            candidate = candidateDay.replace(hour=hour, minute=minute)
                            if LASTRUN < candidate <= TIME:
                                return True
                        except ValueError:
                            continue  # Skip invalid times like Feb 30
            currentDate += timedelta(days=1)

        return False





        


class Destination:
    def __init__(self, source_path, dest_path, config):
        self.source_path = source_path
        self.dest_path = dest_path
        self.method = config['method']['type']
        self.interval = Interval(config['intervals'])

        # Check to see if backup is needed for each configured interval
        self.intervalDict = {}
        for interval in self.intervals.keys():
            if (TIME - datetime.timedelta(**{interval:1})) > LASTRUN:
                self.intervalDict[interval] = self.intervals[interval]
    
    





    def backup(self):
        for interval in self.intervalDict.keys():
            interval_backup_location = BACKUP_LOCATION / interval
            interval_backup_dir = interval_backup_location / TIME_STR

            interval_backup_location.mkdir(mode=0o700)
            interval_backup_dir.mkdir(mode=0o700)

            
            


            



class Source:
    def __init__(self, path, destinations):
        self.path = path
        self.walk()
        self.destinations = [Destination(self.path, x, destinations[x]) for x in destinations.keys()]
    
    def walk(self):
        # Create a list of file, timestamp tuples of the directories and files
        # Sort it by path length to ensure the directories and files aren't created out of order later
        self.dirs = sorted([p for p in self.path.rglob('*') if p.is_dir()], key=lambda p: len(p.parts))
        self.dirs = [(p, datetime.datetime.fromtimestamp(p.stat().st_mtime)) for p in self.dirs]

        self.files = sorted([p for p in self.path.rglob('*') if p.is_file()], key=lambda p: len(p.parts))
        self.files = [(p, datetime.datetime.fromtimestamp(p.stat().st_mtime)) for p in self.dirs]


    def backup(self, destinations=None):
        # The check is to allow partial backups to be implemented later
        if not destinations:
            for destination in self.destinations:
                destination.backup()
        else:
            for destination in destinations:
                if destination in vars(self.destinations):
                    destObj = [x for x in self.destinations if x.dest_path == destination]
                    backupMethod = getattr(destObj, 'backup', None)
                    backupMethod()
                else:
                    print(f'Destination {destination} not found in source {self.path}')
                    continue
                




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
        f.write(f'''\n[Unit]\nDescription=Pybackup\nAfter=multi-user.target\n\n[Service]\nExecStart="{SCRIPT_LOCATION} backup"\nRestart=on-failure\nRestartSec=30\n\n[Install]\nWantedBy=multi-user.target''')

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

    sources = [Source(x, config[x]) for x in config.keys()]
    for source in sources: source.backup()

    # Backdate the timestamp a touch to ensure that marginal files aren't missed
    with open(LASTRUN_FILE, 'w') as f:
        f.write(int(TIME.timestamp()) - 2)






if __name__ == "__main__":
    args = parseArgs()

    match args.action:
        case 'install': install()
        case 'uninstall': uninstall()
        case 'backup': backup()
        case 'cleanup': cleanup()
        case 'list': lst()
