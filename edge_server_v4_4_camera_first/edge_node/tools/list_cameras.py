from pathlib import Path
import glob
print('\n'.join(sorted(glob.glob('/dev/video*'))) or 'No /dev/video* devices found')
