import asyncio
from os import system
from time import time

from git import Repo
from git.exc import GitCommandError

from userge import Config, Message, pool, userge

LOG = userge.getLogger(__name__)
CHANNEL = userge.getCLogger(__name__)


@userge.on_cmd(
    "update",
    about={
        "header": "Memeriksa pembaruan untuk Newbie-Bot1",
        "flags": {
            "-pull": "pull updates",
            "-branch": "Default is -alpha",
        },
        "usage": (
            "{tr}update : check updates from default branch\n"
            "{tr}update -[branch_name] : check updates from any branch\n"
            "add -pull if you want to pull updates\n"
        ),
        "examples": "{tr}update -pull",
    },
    del_pre=True,
    allow_channels=False,
)
async def check_update(message: Message):
    """ check or do updates """
    await message.edit("`Memeriksa pembaruan, Mohon tunggu....`")
    if Config.HEROKU_ENV:
        await message.edit(
            "**Heroku App terdeteksi !**, Pembaruan ditunda karena alasan keamaan.\n"
            "BOT mu akan otomatis memperbarui ketika heroku dimulai ulang"
        )
        return
    flags = list(message.flags)
    pull_from_repo = False
    push_to_heroku = False
    branch = "alpha"
    if "pull" in flags:
        pull_from_repo = True
        flags.remove("pull")
    if "push" in flags:
        if not Config.HEROKU_APP:
            await message.err("HEROKU APP : Tidak ditemukan !")
            return
        # push_to_heroku = True
        # flags.remove("push")
    if len(flags) == 1:
        branch = flags[0]
    repo = Repo()
    if branch not in repo.branches:
        await message.err(f"Nama branch tidak valid : {branch}")
        return
    try:
        out = _get_updates(repo, branch)
    except GitCommandError as g_e:
        if "128" in str(g_e):
            system(
                f"git fetch {Config.UPSTREAM_REMOTE} {branch} && git checkout -f {branch}"
            )
            out = _get_updates(repo, branch)
        else:
            await message.err(g_e, del_in=5)
            return
    if not (pull_from_repo or push_to_heroku):
        if out:
            change_log = (
                f"**PEMBARUAN baru tersedia untuk [{branch}]:\n\n📄 CHANGELOG 📄**\n\n"
            )
            await message.edit_or_send_as_file(
                change_log + out, disable_web_page_preview=True
            )
        else:
            await message.edit(
                f"**Newbie-Bot1 sudah terbaru dengan [{branch}]**", del_in=5
            )
        return
    if pull_from_repo:
        if out:
            await message.edit(
                f"`Pembaruan ditemukan umtuk [{branch}], Now pulling...`"
            )
            await _pull_from_repo(repo, branch)
            await CHANNEL.log(
                f"**PULLED update from [{branch}]:\n\n📄 CHANGELOG 📄**\n\n{out}"
            )
            if not push_to_heroku:
                await message.edit(
                    "**USERGE-X Successfully Updated!**\n"
                    "`Now restarting... Wait for a while!`",
                    del_in=3,
                )
                asyncio.get_event_loop().create_task(userge.restart(True))
        elif push_to_heroku:
            await _pull_from_repo(repo, branch)
        else:
            active = repo.active_branch.name
            if active == branch:
                await message.err(f"already in [{branch}]!")
                return
            await message.edit(
                f"`Moving HEAD from [{active}] >>> [{branch}] ...`", parse_mode="md"
            )
            await _pull_from_repo(repo, branch)
            await CHANNEL.log(f"`Moved HEAD from [{active}] >>> [{branch}] !`")
            await message.edit("`Now restarting... Wait for a while!`", del_in=3)
            asyncio.get_event_loop().create_task(userge.restart())
    if push_to_heroku:
        await _push_to_heroku(message, repo, branch)


def _get_updates(repo: Repo, branch: str) -> str:
    repo.remote(Config.UPSTREAM_REMOTE).fetch(branch)
    upst = Config.UPSTREAM_REPO.rstrip("/")
    out = ""
    upst = Config.UPSTREAM_REPO.rstrip("/")
    for i in repo.iter_commits(f"HEAD..{Config.UPSTREAM_REMOTE}/{branch}"):
        out += f"🔨 **#{i.count()}** : [{i.summary}]({upst}/commit/{i}) 👷 __{i.author}__\n\n"
    return out


async def _pull_from_repo(repo: Repo, branch: str) -> None:
    repo.git.checkout(branch, force=True)
    repo.git.reset("--hard", branch)
    repo.remote(Config.UPSTREAM_REMOTE).pull(branch, force=True)
    await asyncio.sleep(1)


async def _push_to_heroku(msg: Message, repo: Repo, branch: str) -> None:
    sent = await msg.edit(
        f"`Sekarang mendorong pembaruan dari [{branch}] ke heroku...\n"
        "Ini membutuhkan waktu 5 menit`\n\n"
        f"* **MULAI ULANG** setelah 5 menit menggunakan `{Config.CMD_TRIGGER}restart -h`\n\n"
        "* Setelah berhasil memulai ulang, periksa pembaruan lagi :)"
    )
    try:
        await _heroku_helper(sent, repo, branch)
    except GitCommandError as g_e:
        LOG.exception(g_e)
    else:
        await sent.edit(
            f"**HEROKU APP : {Config.HEROKU_APP.name} sudah terbaru dengan [{branch}]**"
        )


@pool.run_in_thread
def _heroku_helper(sent: Message, repo: Repo, branch: str) -> None:
    start_time = time()
    edited = False

    def progress(op_code, cur_count, max_count=None, message=""):
        nonlocal start_time, edited
        prog = f"**code:** `{op_code}` **cur:** `{cur_count}`"
        if max_count:
            prog += f" **max:** `{max_count}`"
        if message:
            prog += f" || `{message}`"
        LOG.debug(prog)
        now = time()
        if not edited or (now - start_time) > 3 or message:
            edited = True
            start_time = now
            userge.loop.create_task(sent.try_to_edit(f"{cur_msg}\n\n{prog}"))

    cur_msg = sent.text.html
    repo.remote("heroku").push(
        refspec=f"{branch}:master", progress=progress, force=True
    )
