"""F7 skill import reuses the existing read-only foreground game capture."""
from manual_potentials import capture_current_game
from skill_reader import read_manual_skills,apply_skills


def process_capture(scanner,image,records,directory):
    snapshot=read_manual_skills(scanner,image,directory,records)
    count,unresolved=apply_skills(records,snapshot)
    return snapshot,count,unresolved
