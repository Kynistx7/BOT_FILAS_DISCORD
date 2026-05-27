from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'bot.py'
s = p.read_text(encoding='utf-8')
start_key = 'from database import Base, engine'
end_key = 'print(f"Erro no anti-pix: {e}")'
si = s.find(start_key)
if si != -1:
    ei = s.find(end_key, si)
    if ei != -1:
        ei_end = s.find('\n', ei)
        if ei_end == -1:
            ei_end = ei + len(end_key)
        new = s[:si] + '\n# Banco gerenciado por database_v2 (init_db() é chamado mais abaixo)\n' + s[ei_end+1:]
        p.write_text(new, encoding='utf-8')
        print('Removed duplicate DB/init and first on_message block')
    else:
        print('End key not found; no changes made')
else:
    print('Start key not found; no changes made')
