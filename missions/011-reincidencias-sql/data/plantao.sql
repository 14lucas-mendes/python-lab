CREATE TABLE equipamentos (
    codigo TEXT PRIMARY KEY,
    nome TEXT NOT NULL
);

CREATE TABLE falhas (
    id INTEGER PRIMARY KEY,
    equipamento TEXT NOT NULL,
    minutos INTEGER NOT NULL,
    FOREIGN KEY (equipamento) REFERENCES equipamentos(codigo)
);

INSERT INTO equipamentos (codigo, nome) VALUES
    ('S01', 'Bomba principal'),
    ('S03', 'Ventilador leste'),
    ('S09', 'Sensor de porta');

INSERT INTO falhas (equipamento, minutos) VALUES
    ('S01', 40),
    ('S01', 10),
    ('S01', 5),
    ('S03', 15),
    ('S03', 20);
