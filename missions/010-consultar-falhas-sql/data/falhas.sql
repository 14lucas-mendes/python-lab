CREATE TABLE falhas (
    id INTEGER PRIMARY KEY,
    equipamento TEXT NOT NULL,
    minutos INTEGER NOT NULL,
    registrado_em TEXT NOT NULL
);

INSERT INTO falhas (equipamento, minutos, registrado_em) VALUES
    ('S01', 40, '2026-03-01'),
    ('S03', 15, '2026-03-02'),
    ('S01', 10, '2026-03-03');
