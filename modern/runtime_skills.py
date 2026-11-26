"""Bind a private reader instance to a downloaded data directory.

The legacy module and its function defaults remain unchanged for the old app.
"""
from functools import partial
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path


class RuntimeSkills:
    def __init__(self,directory,source_root):
        spec=spec_from_file_location('_cpbv_downloaded_skill_reader',Path(source_root)/'skill_reader.py')
        self.reader=module_from_spec(spec);spec.loader.exec_module(self.reader)
        self.directory=Path(directory);self.catalog=self.reader.SkillCatalog(self.directory)
        # Existing read_manual_skills calls its own module's read_skills global.
        self.reader.read_skills=partial(self.reader.read_skills,directory=self.directory)

    def process_capture(self,scanner,image,records,directory):
        snapshot=self.reader.read_manual_skills(scanner,image,directory,records)
        count,unresolved=self.reader.apply_skills(records,snapshot)
        return snapshot,count,unresolved
