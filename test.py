import pandas as pd

student = pd.read_csv("students.csv")
student.head()

result = student(["age"] > 18 & ["score"] > 70)
