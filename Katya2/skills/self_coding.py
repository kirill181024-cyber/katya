from core import self_coder


def learn(task):
    return self_coder.generate(task)


ACTIONS = {
    "self.code": {
        "func": learn,
        "desc": "Самообучение: если нужного навыка нет — сгенерировать новый Python-плагин под задачу",
        "params": {"task": "что должна уметь Катя"},
    },
}
