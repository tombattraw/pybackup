PyBackup

A backup management project written in Python. Run "./pybackup install" to get started, then edit the config file /etc/pybackup/config.yaml to configure what's backed up where.

Currently, nothing works. I'll first implement copies to mounted file systems like NFS or SMB, then work on mounting and unmounting at need, then rsync, then add key or password SCP support.

The top-level configuration is in /etc/pybackup.yaml, and must be edited with root. This controls whose "$HOME/backupconfig.yaml" files will be read and backed up.

Example:
authorized_users:
  - username: "user1"
    quota: "10%"
    allowed_dirs:
      - "/home/user1"
      - "/opt/"

Each user backup job will be executed as that user to prevent permission issues. This does mean that any files only readable by root must be backed up by root.
The upside is that Linux has decades of experience managing permissions and preventing privilege escalations, and I do not.

The basic unit of the user configuration is the Source. This is a directory somewhere in your system that you wish to back up. Each source has one or many Destinations, where its files will be backed up to.

Each Destination has a Method and a set of Intervals.

A Method is the means by which the files will be backed up. This includes the type (direct copy to mounted file system, rsync, SCP, etc) and the credential/key to enable the transfer.

An Interval uses cron syntax to allow tiered backups.

Example:
source:
  - path: "/home/user/"
  - destination:
    - path: "/archive/backup/user/"
    - method:
      - type: # [scp, rsync, smb, cp]
      - key: "/home/user/.ssh/id_rsa"
      - username: # "user"
      - password: # "password"
    - interval: "* - * - * - * - *"