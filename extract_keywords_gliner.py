from gliner import GLiNER


def read_file(file_path):
    with open(file_path, 'r', encoding="utf-8", errors="ignore") as file:
        content = file.read()
    return content

context = read_file('example_jobsdb_jobs.json')

model = GLiNER.from_pretrained("urchade/gliner_medium-v2.1")

labels = ["software", "technology", "programming language", "methodology", "concept", "location", "position"]

entities = model.predict_entities(context, labels)

for entity in entities:
    print(entity["text"], "=>", entity["label"])