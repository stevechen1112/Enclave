from app.services.workflow_form_handler import build_form_handler

incident = build_form_handler("incident_report")
handover = build_form_handler("shift_handover")
daily_report = build_form_handler("daily_report")
