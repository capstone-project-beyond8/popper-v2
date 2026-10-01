---
domain: Secondary school exam performance over one term, three schools.
objectives:
  - What drives exam performance among secondary students?
variables:
  exam_score:
    meaning: Final exam score
    unit: points
    type: continuous
    role: outcome
    range: [0, 100]
  study_hours_week:
    meaning: Weekly study time
    unit: hours
    type: continuous
    role: exposure
  student_id:
    type: id
    role: id
  school:
    type: categorical
    role: cluster
design:
  observation_unit: student
  kind: observational
  cluster_column: school
  id_column: student_id
concepts:
  - id: study_effort
    name: Study effort
    definition: Time a student invests in study.
---
# Exam performance

What drives exam performance among secondary students? We suspect study time matters most, but sleep and part-time work may matter too. Data: one term, three schools.

Audience: school administrators.
