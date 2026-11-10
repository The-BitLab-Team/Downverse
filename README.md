# Downverse

Baixe VODs do **Weverse** com legendas e thumbnails, já organizados por artista e data.
Interface plana e moderna, janela própria no Windows e uso opcional pelo terminal.

> Projeto independente, sem vínculo com a Weverse Company. Use só para uso pessoal e respeite os
> termos do Weverse. O Downverse **não burla DRM**: conteúdo protegido é recusado com um aviso claro.

## O que faz

- **Uma live ou o canal inteiro.** Cole o link de uma live para baixar só ela, ou o link do canal do artista/grupo para listar todas as lives e escolher quais baixar (filtro por membro, por período e por título).
- **Você escolhe a qualidade:** melhor disponível, até 1080p, 720p, 480p, 360p ou menor tamanho.
- **Legendas e thumbnail opcionais.** Legendas em SRT (abre em qualquer editor) ou VTT, em todos os idiomas disponíveis ou só nos que você marcar. A thumbnail é salva em JPG.
- **Pastas organizadas** dentro da pasta Vídeos do computador (veja abaixo).
- **Fila de downloads** estilo kanban (na fila, baixando, finalizados), com progresso, cancelar e tentar de novo.
- **Biblioteca** com o que já foi baixado: abre a pasta, reproduz e evita baixar a mesma live duas vezes.
- Tema claro e escuro, tudo em português do Brasil.

## Como as pastas ficam

```
Vídeos/
└─ Weverse/
   ├─ TAEYEON/                        ← artista solo
   │  └─ 2026-03-10/
   │     ├─ Título da live.mp4
   │     ├─ Título da live.jpg        ← thumbnail, solta ao lado do vídeo
   │     └─ Legendas/
   │        └─ Título da live.pt_BR.srt
   └─ LE SSERAFIM/                    ← grupo
      ├─ 2026-03-10/                  ← live da conta oficial do grupo (sem pasta de membro)
      └─ 채원/                         ← membro que fez a live
         └─ 2026-03-15/
            ├─ Título da live.mp4
            ├─ Título da live.jpg
            └─ Legendas/
```

- A pasta do membro só é criada quando ele não é a própria conta do canal. Em **Configurações** dá para forçar "sempre" ou "nunca" (útil para artistas solo).
- A data da live segue o fuso do seu computador. Dá para trocar para UTC ou horário da Coreia.
- Duas lives no mesmo dia: a segunda vai para `2026-03-15 (2)`, e assim por diante.
- Nomes de pastas e arquivos são limpos de caracteres que o Windows não aceita.

## Links aceitos

| Você cola | O que acontece |
| --- | --- |
| `weverse.io/lesserafim` (página inicial do canal) | lista **todas as lives** do canal |
| `weverse.io/lesserafim/live` (página de lives) | lista **todas as lives** do canal |
| `weverse.io/lesserafim/live/2-123456789` | baixa **só essa live** |
| `weverse.io/lesserafim/media/2-123456789` | baixa só esse vídeo |

O Downverse aceita o link com ou sem `https://`, com `www.` ou `m.`, com prefixo de idioma (`/ko/`), com `?hl=ko` ou `#…` no fim, em maiúsculas e até colado no meio de um texto. Links de outros sites, da loja, de Moments e similares são recusados com uma explicação.

## Usar no Windows

1. Instale o [Python 3.10 ou mais novo](https://www.python.org/downloads/), marcando **Add python.exe to PATH**.
2. Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele cria o ambiente e instala as dependências; depois abre direto.
   Se algo falhar, rode `iniciar.bat debug` para ver as mensagens.

### Criar o instalador (Setup.exe)

Dê dois cliques em **`criar_instalador.bat`**. Ele:

1. prepara o ambiente e instala o PyInstaller;
2. gera o programa em `dist\Downverse\Downverse.exe` (FFmpeg e interface já embutidos);
3. monta o instalador com o [Inno Setup](https://jrsoftware.org/isinfo.php) em **`dist\Downverse-Setup-<versão>.exe`**
   (se o Inno Setup não estiver instalado, tenta instalar pelo `winget`; sem ele, gera um `.zip` portátil).

O instalador funciona sem permissão de administrador, cria atalhos no Menu Iniciar e (opcional) na Área de Trabalho, e tem desinstalador.

## Usar em Linux ou macOS

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m downverse
```

Sem o `pywebview` (ou no Linux) o Downverse abre no navegador padrão. Para forçar isso: `python -m downverse gui --browser`.

## Entrar na conta Weverse

O Weverse exige login para quase todos os VODs. A sua senha **nunca** passa pelo Downverse; ele usa a sessão que você já tem no navegador. Na aba **Conta Weverse**:

1. Entre em `weverse.io` no seu navegador (vale Google, Apple, e-mail…).
2. Escolha o mesmo navegador no Downverse e deixe **Cookies do navegador** marcado.
3. Clique em **Testar conexão**.

Alternativas: **arquivo `cookies.txt`** exportado com uma extensão do navegador, ou **token de atualização** (valor do cookie `we2_refresh_token`). No Chrome e no Edge recentes, ler os cookies pode falhar no Windows; nesse caso use o Firefox ou o `cookies.txt`.

## Pelo terminal

```bash
python -m downverse download https://weverse.io/lesserafim -q 720 --langs pt,en
python -m downverse download https://weverse.io/lesserafim/live/2-123456789 --no-thumb
```

Opções: `-q/--quality`, `--no-subs`, `--langs`, `--no-thumb`, `-o/--output`, `--solo`, `--overwrite`. As demais configurações vêm do app (aba Configurações).

## Desenvolvimento

```bash
pip install -r requirements.txt pytest
python -m pytest                      # testes: links, pastas, pipeline completo e servidor
python scripts/demo_server.py         # abre a interface contra um Weverse simulado, sem internet nem conta
```

Os testes rodam o extrator **real** do yt-dlp contra respostas simuladas do Weverse, para validar pastas, qualidade, legendas e thumbnails sem depender da rede. Como o Weverse exige login, o fluxo contra o site de verdade precisa ser conferido com a sua conta.

Estrutura: `downverse/links.py` (tratamento de links), `paths.py` (hierarquia de pastas), `engine.py` (yt-dlp), `manager.py` (fila), `server.py` (API local protegida por token) e `ui/` (interface). Mantenha o yt-dlp atualizado (`pip install -U yt-dlp`), porque o Weverse muda com frequência.

## Licença e créditos

A fonte Plus Jakarta Sans (OFL) e os ícones Lucide (ISC) estão incluídos na pasta `ui/`. Os downloads usam o [yt-dlp](https://github.com/yt-dlp/yt-dlp).
