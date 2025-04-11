PyBackup

A backup management project written in Python. Run "./pybackup install" to get started, then edit the config file /etc/pybackup/config.yaml to configure what's backed up where.

Currently, nothing works. I'll first implement copies to mounted file systems like NFS or SMB, then work on mounting and unmounting at need, then rsync, then add key or password SCP support.

Eventually, user-specific configurations will be implemented as well. The root user will be able to specify user-specific config file locations in the main config, which will then be read and handled without root permissions.

The basic unit of the configuration is the Source. This is a directory somewhere in your system that you wish to back up. Each source has one or many Destinations, where its files will be backed up to.

Each Destination has a Method and a set of Intervals.

A Method is the means by which the files will be backed up. This includes the type (direct copy to mounted file system, rsync, SCP, etc) and the credential/key to enable the transfer.

An Interval is at which points you want the files backed up, anywhere from integer minutes to years. This allows tiered backups, with separate limits and schedules for each interval if desired.
    Eventually, cronjob+limit syntax will be added, something to the tune of */6: 10 to mean every 6th interval to a limit of 10, or 3: 5 to mean the third minute/hour/whatever to a limit of 5.
    Eventually, I'll implement incremental backups on a per-interval basis


source:
  - path: "/home/user/"
  - destination:
    - path: "/archive/backup/user/"
    - method:
      - type: # [scp, rsync, smb, cp]
      - key: "/home/user/.ssh/id_rsa"
      - username: user
      - password: "password"
    - intervals:
      - minutes:
      - hours: */6: 4
      - days: */7: 7
      - weeks: 
      - months:
      - years: *: 5