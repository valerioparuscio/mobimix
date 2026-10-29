"""Words shared by the services that explain themselves to the user (in Italian)."""

from app.models import Purpose

# How a kind of mission is named in the middle of a sentence ("per il tragitto casa-lavoro...").
PURPOSE_NAMES = {
    Purpose.COMMUTE: "il tragitto casa-lavoro",
    Purpose.STUDY: "il tragitto casa-scuola o università",
    Purpose.SCHOOL_ESCORT: "l'accompagnamento a scuola",
    Purpose.SHOPPING: "la spesa e le commissioni",
    Purpose.LOCAL_LEISURE: "lo svago in zona",
    Purpose.WEEKEND: "le gite del weekend",
    Purpose.FAMILY_VISIT: "le visite a familiari",
    Purpose.HOLIDAY: "le vacanze",
    Purpose.BUSINESS: "i viaggi di lavoro",
    Purpose.LONG_DISTANCE: "i weekend lunghi",
    Purpose.OTHER: "gli altri spostamenti",
}
