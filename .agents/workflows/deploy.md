---
description: Sincroniza o código local com o GitHub e atualiza o servidor no Homelab (100.100.10.240)
---

Este workflow automatiza o envio das alterações locais para o repositório remoto e dispara a atualização no servidor remoto via SSH.

### Passos de Execução:

1. Adiciona todos os arquivos alterados ao stage do Git.
// turbo
```bash
git add .
```

2. Cria um commit com uma mensagem descritiva baseada nas últimas alterações.
*(Dica: se pedir /deploy "minha mensagem", eu usarei esse texto)*
// turbo
```bash
git commit -m "Arquitetura atualizada: separação de database e metadata"
```

3. Envia o código para o branch principal no GitHub.
// turbo
```bash
git push origin main
```

4. Conecta via SSH no Homelab (100.100.10.240), baixa o novo código e reconstrói o container Docker.
// turbo
```bash
ssh -i /Users/guilsmatos/.gemini/tmp/datamanager/casaos_key -o StrictHostKeyChecking=no guilsmatos@100.100.10.240 "cd ~/apps/DataManager && git pull && docker compose up -d --build"
```
