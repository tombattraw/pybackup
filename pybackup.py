#!/usr/bin/env python3

import os, hashlib, pathlib, argparse, yaml, sys, pwd, subprocess, datetime, shutil, gzip, calendar
from collections import OrderedDict

CONFIG_LOCATION = pathlib.Path('/etc/pybackup')
CONFIG_FILE = CONFIG_LOCATION / 'config.yaml'
SCRIPT_LOCATION = pathlib.Path('/bin/pybackup.py')
BACKUP_LOCATION = pathlib.Path('/opt/backups')
SERVICE_PATH = pathlib.Path('/etc/systemd/system/pybackup.service')
IS_ROOT = os.geteuid() == 0
UID = os.geteuid()
TIME = datetime.datetime.now().replace(second=0, microsecond=0)
TIME_STR = TIME.strftime('%Y-%m-%d_%H:%M')
LASTRUN_FILE = BACKUP_LOCATION / 'lastrun.txt'

try:
    with open(LASTRUN_FILE, 'r') as f:
        LASTRUN = datetime.datetime.fromtimestamp(int(f.read()))
except FileNotFoundError:
    LASTRUN = datetime.datetime.fromtimestamp(0)


class Interval:
    # Takes a cron-style string "*/5 - 1,3,7 - 30 - 10-12 - *"
    # Intended use is to verify validity when instantiated, then check if the next backup should be started using "<object>.should_backup()"

    def __init__(self, cron_string):
        self.FIELD_NAMES = ['minute', 'hour', 'dayOfMonth', 'month', 'dayOfWeek']
        self._interval_dict = OrderedDict.fromkeys(self.FIELD_NAMES)

        self._valid_ranges = {
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

        fields = cron_string.strip().split()
        if len(fields) != 5:
            raise ValueError("Cron string must have exactly 5 fields")

        for name, value in zip(self.FIELD_NAMES, fields):
            self._interval_dict[name] = self._parse_interval(name, value)


    def _parse_interval(self, interval_type, interval_string):
        # Takes a cron-style string for a given interval: "*/5", "1,3,7", or "2-6"
        # Returns a list of valid values
        # Raises ValueErrors if given values are out of range

        valid_min = self._valid_ranges[interval_type][0]
        valid_max = self._valid_ranges[interval_type][-1]
        valid_range = self._valid_ranges[interval_type]

        # "/" used to set step value
        values = []
        if '/' in interval_string:
            if interval_string.count('/') > 1:
                raise ValueError('Can only have one "/" in interval')
            interval_string, step = interval_string.split('/')
            step = int(step)
        else:
            step = 1
        
        # "," used to denote lists of values
        # unparsed_values is a list of strings, parsed_values is a list of integers generated from the strings
        unparsed_values = interval_string.split(',')
        parsed_values = []

        for uV in unparsed_values:
            # "-" used to denote ranges
            if '-' in uV:
                if uV.count('-') > 1:
                    raise ValueError('Can only have one "-" in range')
                
                beginning, end = uV.split('-')
                if int(beginning) < valid_min:
                    raise ValueError(f'{beginning} too low for the {interval_type} range')
                if int(end) < int(beginning):
                    raise ValueError(f'{end} is greater than {beginning} for the {interval_type} range')

                # Silently correcting to avoid usually-valid date overruns like a 30 overflowing Feb 28
                end = int(end) if int(end) in valid_range else valid_max
                parsed_values.extend(range(int(beginning), int(end)+1, step))

            # "*" used to mean every valid value
            elif uV == '*':
                parsed_values.extend(range(valid_min, valid_max+1, step))

            else:
                if int(uV) not in valid_range:
                    raise ValueError(f'{uV} out of range for {interval_type}')
                parsed_values.append(int(uV))
        
        return sorted(list(set(parsed_values)))
                

    def should_backup(self):
        # Accepts no input
        # Returns True if the source has had a backup interval elapse since the script was last run, else False.
        current_date = LASTRUN.date()
        end_date = TIME.date()

        while current_date <= end_date:
            # Only check days that match the cron constraints
            candidate_day = datetime.datetime.combine(current_date, datetime.datetime.min.time())
            
            if (candidate_day.month in self._interval_dict['month'] and
                candidate_day.day in self._interval_dict['dayOfMonth'] and
                (candidate_day.weekday() in self._interval_dict['dayOfWeek'] or
                 (7 in self._interval_dict['dayOfWeek'] and candidate_day.weekday() == 6))):

                # Now check each valid hour/minute on this day
                for hour in self._interval_dict['hour']:
                    for minute in self._interval_dict['minute']:
                        try:
                            candidate = candidate_day.replace(hour=hour, minute=minute)
                            if LASTRUN < candidate <= TIME:
                                return True
                        except ValueError:
                            continue  # Skip invalid times like Feb 30
            current_date += datetime.timedelta(days=1)

        return False


class Destination:
    def __init__(self, source_path, dest_path, config):
        self.source_path = source_path
        self.dest_path = dest_path
        self.method = config['method']['type']
        self.interval = Interval(config['interval'])
    

    def backup(self):
        if self.interval.should_backup():
            self.method.backup(self.source_path, self.dest_path)





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
                


def restore(): return None
def printlist(): return None
def scheduled(): return None
def cleanup(): return None

def parse_args():
    parser = argparse.ArgumentParser(prog='pybackup.py')

    subparsers = parser.add_subparsers(dest='action', required=True, help='Available actions')

    parser_install = subparsers.add_parser('install', help='Install something')
    parser_install.set_defaults(func=install)

    parser_uninstall = subparsers.add_parser('uninstall', help='Uninstall something')
    parser_uninstall.set_defaults(func=uninstall)

    parser_backup = subparsers.add_parser('backup', help='Backup files or directories')
    parser_backup.add_argument('--target', required=True, help='Target directory or file to back up')
    parser_backup.set_defaults(func=backup)

    parser_restore = subparsers.add_parser('restore', help='Restore from a backup')
    parser_restore.add_argument('--id', required=True, help='ID of the backup to restore')
    parser_restore.set_defaults(func=restore)

    parser_cleanup = subparsers.add_parser('cleanup', help='Cleanup old backups')
    parser_cleanup.add_argument('--id', required=False, help='ID of the backup to remove')
    parser_cleanup.add_argument('--all', required=False, help='Purge all backups from given source')
    parser_cleanup.set_defaults(func=cleanup)

    parser_list = subparsers.add_parser('list', help='List backups')
    parser_list.set_defaults(func=printlist)

    parser_scheduled = subparsers.add_parser('scheduled', help='Run quietly as if by a scheduler')
    parser_scheduled.set_defaults(func=scheduled)

    return parser.parse_args()


def install():
    if not IS_ROOT:
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
    if not IS_ROOT:
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
        f.write(str(TIME.timestamp() - 2))






if __name__ == "__main__":
    args = parse_args()
    args.func(args)
