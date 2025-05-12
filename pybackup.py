#!/usr/bin/env python3

import argparse
import calendar
import os
import pwd
import shutil
import subprocess
import sys
import yaml
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_LOCATION: Path = Path('/etc/pybackup')
CONFIG_FILE: Path = CONFIG_LOCATION / 'pybackup.yaml'
SCRIPT_LOCATION: Path = Path('/bin/pybackup.py')
BACKUP_LOCATION: Path = Path('/opt/backups')
SERVICE_PATH: Path = Path('/etc/systemd/system/pybackup.service')
LASTRUN_FILE: Path = BACKUP_LOCATION / 'lastrun.txt'

START_TIME: datetime = datetime.now().replace(second=0, microsecond=0)
START_TIME_STR: str = START_TIME.strftime('%Y-%m-%d_%H:%M')

try:
    with open(LASTRUN_FILE, 'r') as g:
        LASTRUN: datetime = datetime.fromtimestamp(int(g.read()))
except FileNotFoundError:
    LASTRUN: datetime = datetime.fromtimestamp(0)


class Interval:
    # Takes a cron-style string "*/5 1,3,7 30 10-12 *"
    # Intended use is to verify validity when instantiated, then check if the next backup should be started using "<object>.should_backup()"
    # Relies on global START_TIME at construction; needed to correctly set the max days of the month

    FIELD_NAMES: list[str] = ['minute', 'hour', 'day_of_month', 'month', 'day_of_week']

    def __init__(self, cron_string: str):
        self._interval_dict: OrderedDict[str, list[int]] = OrderedDict.fromkeys(self.FIELD_NAMES)

        self._valid_ranges: dict[str, range] = {
            'minute': range(0, 60),
            'hour': range(0, 24),
            'day_of_month': range(1, calendar.monthrange(START_TIME.year, START_TIME.month)[1]+1),
            'month': range(1, 13),
            'day_of_week': range(0, 8) # 0 and 7 are both Sunday
        }

        self._parse_cron_string(cron_string)

    def _parse_cron_string(self, cron_string: str):
        # Takes a cron-style string
        # Raises ValueErrors if the number of fields is incorrect
        # Returns lists of valid ints for each interval

        fields = cron_string.strip().split()
        if len(fields) != 5:
            raise ValueError("Cron string must have exactly 5 fields")

        for name, value in zip(self.FIELD_NAMES, fields):
            self._interval_dict[name] = self._parse_interval(name, value)


    def _parse_interval(self, interval_type: str, interval_string: str) -> list[int]:
        # Takes a cron-style string for a given interval: "*/5", "1,3,7", or "2-6"
        # Returns a list of valid values
        # Raises ValueErrors if given values are out of range

        valid_min = self._valid_ranges[interval_type][0]
        valid_max = self._valid_ranges[interval_type][-1]
        valid_range = self._valid_ranges[interval_type]

        # "/" used to set step value
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

        for u_val in unparsed_values:
            # "-" used to denote ranges
            if '-' in u_val:
                if u_val.count('-') > 1:
                    raise ValueError('Can only have one "-" in range')
                
                beginning, end = u_val.split('-')
                if int(beginning) < valid_min:
                    raise ValueError(f'{beginning} too low for the {interval_type} range')
                if int(end) < int(beginning):
                    raise ValueError(f'{end} is greater than {beginning} for the {interval_type} range')

                # Silently correcting to avoid usually-valid date overruns like a 30 overflowing Feb 28
                end = int(end) if int(end) in valid_range else valid_max
                parsed_values.extend(range(int(beginning), int(end)+1, step))

            # "*" used to mean every valid value
            elif u_val == '*':
                parsed_values.extend(range(valid_min, valid_max+1, step))

            else:
                if int(u_val) not in valid_range:
                    raise ValueError(f'{u_val} out of range for {interval_type}')
                parsed_values.append(int(u_val))
        
        return sorted(set(parsed_values))

    def should_backup(self) -> bool:
        # Returns True if the source has had a backup interval elapse since the script was last run, else False.
        current_date = LASTRUN.date()
        end_date = START_TIME.date()

        while current_date <= end_date:
            # Only check days that match the cron constraints
            candidate_day = datetime.combine(current_date, datetime.min.time())
            
            if (candidate_day.month in self._interval_dict['month'] and
                candidate_day.day in self._interval_dict['day_of_month'] and
                (candidate_day.weekday() in self._interval_dict['day_of_week'] or
                 (7 in self._interval_dict['day_of_week'] and candidate_day.weekday() == 6))):

                # Now check each valid hour/minute on this day
                for hour in self._interval_dict['hour']:
                    for minute in self._interval_dict['minute']:
                        try:
                            candidate = candidate_day.replace(hour=hour, minute=minute)
                            if LASTRUN < candidate <= START_TIME:
                                return True
                        except ValueError:
                            continue  # Skip invalid times like Feb 30
            current_date += timedelta(days=1)

        return False


class Destination:
    # Represents a destination path to back up to and a means of getting there
    def __init__(self, source_path: Path, config: dict):
        self.source_path = source_path
        self.config = config
        self.method = config['method']['type']
        self.path = config['path']
        self.interval = Interval(config['interval'])
    

    def backup(self):
        if self.interval.should_backup():
            self.method.backup(self.source_path, self.path)


class Source:
    # Represents a directory on the local system and all contents and subdirectories
    def __init__(self, path: Path, destinations: list[dict[dict]]):
        self.path = path
        self.dirs = []
        self.files = []

        self.destinations: list[Destination] = [Destination(self.path, x) for x in destinations]


    def _walk(self) -> None:
        # Create a list of file, timestamp tuples of the directories and files
        # Sort it by path length to ensure the directories and files aren't created out of order later
        dirs = sorted([p for p in self.path.rglob('*') if p.is_dir()], key=lambda p: len(p.parts))
        self.dirs: list[tuple[Path, datetime]] = [(p, datetime.fromtimestamp(p.stat().st_mtime)) for p in dirs]

        files = sorted([p for p in self.path.rglob('*') if p.is_file()], key=lambda p: len(p.parts))
        self.files: list[tuple[Path, datetime]] = [(p, datetime.fromtimestamp(p[0].stat().st_mtime)) for p in files]


    def backup(self, destinations=None):
        # First, get an idea for what's in the directory and needs to be backed up
        self._walk()

        # The check is to allow partial backups to be implemented later
        if not destinations:
            for destination in self.destinations:
                destination.backup()
        else:
            for destination in destinations:
                if destination in vars(self.destinations):
                    dest_obj = [x for x in self.destinations if x.dest_path == destination]
                    backup_method = getattr(dest_obj, 'backup', None)
                    backup_method()
                else:
                    print(f'Destination {destination} not found in source {self.path}')
                    continue
                

def check_backup_permissions(target_user: str, targets: list[Path]) -> bool:
    # Takes a user to back up as, and the directory back up
    # Throws a PermissionError if not authorized, returns True if authorized to make script logic flow more naturally
    current_uid = os.getuid()
    current_user = pwd.getpwuid(current_uid).pw_name

    # Check permissions in config. Root gets a shortcut.
    if current_uid == 0:
        return True

    with open(CONFIG_FILE, 'r') as f:
        global_config = yaml.safe_load(f)

    # First check user permissions
    # non-root isn't allowed to use --user for anyone but themselves
    if current_user not in global_config['authorized_users'].keys():
        raise PermissionError(f'User {current_user} not allowed to back up. Ask an admin for assistance')

    if not target_user == current_user:
        raise PermissionError('Non-root users cannot run backups for other users')

    # Then check directory permissions
    # "/" is the setting to disable directory checks
    user_config = global_config['authorized_users'].get(target_user)
    if not user_config:
        raise PermissionError(f"No config found for user {target_user}")

    allowed_dirs = [Path(x).resolve() for x in user_config.get('allowed_dirs', [])]

    if Path('/').resolve() in allowed_dirs:
        return True

    for target in targets:
        target_path = target.resolve()
        if not any(target_path.is_relative_to(p) for p in allowed_dirs):
            raise PermissionError(f'{target_path} is not inside an allowed backup directory. Ask an admin for assistance')

    return True



def restore(): return None
def printlist(): return None
def scheduled(): return None
def cleanup(): return None


def is_existing_dir(path_str: str) -> list[Path]:
    # Checks validity of the path, returns it as a Path object inside a list to match the default
    path = Path(path_str)
    if not path.is_dir():
        raise argparse.ArgumentTypeError(f'{path_str} does not exist or is not a directory')
    return [path]


def is_valid_user(username: str) -> str:
    if not username in [x.pw_name for x in pwd.getpwall()]:
        raise argparse.ArgumentTypeError(f'{username} not an existing user')
    return username


def parse_args():
    parser = argparse.ArgumentParser(prog='pybackup.py')

    subparsers = parser.add_subparsers(dest='action', required=True, help='Available actions')

    parser_install = subparsers.add_parser('install', help='Install as a service')
    parser_install.set_defaults(func=install)

    parser_uninstall = subparsers.add_parser('uninstall', help='Uninstall as a service')
    parser_uninstall.set_defaults(func=uninstall)

    parser_backup = subparsers.add_parser('backup', help='Backup directories')
    parser_backup.add_argument('--target', required=False, help=f'Target directory or file to back up. Default is all allowed in {CONFIG_FILE}', type=is_existing_dir)
    parser_backup.add_argument('--user', required=False, help='Run backup for specified user. Requires root', type=is_valid_user, default=pwd.getpwuid(os.getuid()).pw_name)
    parser_backup.add_argument('--all', required=False, help='Run backup for all users. Requires root', action='store_true')
    parser_backup.add_argument('--type', required=False, help='Only back up to destinations using this given method', choices=['scp', 'cp', 'rsync', 'smb'])
    parser_backup.set_defaults(func=backup)

    parser_restore = subparsers.add_parser('restore', help='Restore from a backup')
    parser_restore.add_argument('--id', required=False, help='ID of the backup to restore. If not given, assume latest backup')
    parser_restore.add_argument('--source', required=False, help='Source to restore. If not given, assume all should be restored from latest')
    parser_restore.set_defaults(func=restore)

    parser_cleanup = subparsers.add_parser('cleanup', help='Cleanup old backups')
    parser_cleanup.add_argument('--id', required=False, help='ID of the backup to remove')
    parser_cleanup.add_argument('--user', required=False, help='Clean backups belonging to given user. Requires root', type=is_valid_user, default=pwd.getpwuid(os.getuid()).pw_name)
    parser_cleanup.add_argument('--all', required=False, help='Remove all backups from given source')
    parser_cleanup.set_defaults(func=cleanup)

    parser_list = subparsers.add_parser('list', help='List backups')
    parser_list.add_argument('--user', required=False, help='List backups belonging to given user. Requires root', type=is_valid_user, default=pwd.getpwuid(os.getuid()).pw_name)
    parser_list.set_defaults(func=printlist)

    parser_scheduled = subparsers.add_parser('scheduled', help='Run quietly as if by a scheduler')
    parser_scheduled.set_defaults(func=scheduled)

    return parser.parse_args()


def install():
    if not (os.getuid() == 0):
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

    SCRIPT_LOCATION.write_bytes(Path(sys.argv[0]).read_bytes())
    SCRIPT_LOCATION.chmod(mode=0o755)

    with open(LASTRUN_FILE, 'w') as f:
        f.write('0')

    with open(SERVICE_PATH, 'w') as f:
        f.write(f'''\n[Unit]\nDescription=Pybackup\nAfter=multi-user.target\n\n[Service]\nExecStart="{SCRIPT_LOCATION} backup"\nRestart=on-failure\nRestartSec=30\n\n[Install]\nWantedBy=multi-user.target''')

    SERVICE_PATH.chmod(mode=0o644)

    Path('/etc/systemd/system/multi-user.target.wants/pybackup.service').symlink_to(SERVICE_PATH)

    subprocess.run('systemctl daemon-reload')

    print('Installation complete')


def uninstall():
    if not (os.getuid == 0):
        print('Uninstallation must be done with root permissions')
        sys.exit()

    for file in [CONFIG_FILE, CONFIG_LOCATION, SCRIPT_LOCATION, SERVICE_PATH, Path('/etc/systemd/system/multi-user.target.wants/pybackup.service')]:
        file.unlink()

    remove = input('Delete backups? [y/N] ')
    if remove.lower().strip() == 'y':
        
        shutil.rmtree(BACKUP_LOCATION)

    CONFIG_LOCATION.rmdir()

    print('Uninstallation complete')


def backup(args):
    if not check_backup_permissions(args.backup.user, args.backup.target):
        raise PermissionError('Action not authorized')

    effective_uid = pwd.getpwnam(args.backup.user).pw_uid
    home_dir = Path(pwd.getpwuid(effective_uid).pw_dir)

    with open(home_dir / 'backupconfig.yaml') as f:
        backup_config = yaml.safe_load(f)

    # If a backup target isn't explicitly given, backup everything allowed
    targets: list[dict]
    if not args.backup.target:
        sources: list[dict] = backup_config['source']

        for source in sources:
            if not source['path'].exists():
                raise FileExistsError(f'Backup source {source['path']} does not exist')

    # Otherwise, check the config to see which method, destination, and other details are applicable
    # Normalize to a list of dictionaries to match the other possibility
    # The existence check is done in argparse, so no need to match
    else:
        for source in backup_config['source']:
            if Path(args.backup.target).is_relative_to(Path(source['path'])):
                targets = [source]
                targets[0]['path'] = args.backup.target
                break
























if __name__ == "__main__":
    args = parse_args()

    args.func(args)
