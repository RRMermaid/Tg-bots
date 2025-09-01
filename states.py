from enum import IntEnum

class BotState(IntEnum):
    ASK_CONTACT = 0
    ASK_MORNING_HOUR = 2
    ASK_EVENING_HOUR = 3
    ASK_NAME = 4
    ASK_GENDER = 5
    ASK_AGE = 6
    ASK_WEIGHT = 7
    ASK_HEIGHT = 8
    ASK_ACTIVITY = 9
    ASK_GOAL = 10
    RECORD_MEAL = 11
    MONITORING = 12
    ASK_LOCAL_TIME = 99
    