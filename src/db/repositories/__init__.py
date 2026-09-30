"""get/write-Zugriffe je Schema. Bewusst ohne delete - die DB wuerde es ohnehin ablehnen.

Repositories committen nicht selbst; die Transaktion steuert der Aufrufer
(``session_scope`` bzw. ``BatchRecorder``).
"""
