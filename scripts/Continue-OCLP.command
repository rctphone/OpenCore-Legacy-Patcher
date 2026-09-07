#!/bin/zsh
set -o pipefail
task_stage="$HOME/OCLP-install"
task_action=$(/usr/bin/python3 - "$task_stage/state.json" <<'STATE'
import json,sys
from pathlib import Path
p=Path(sys.argv[1]); phase=json.loads(p.read_text()).get('phase') if p.exists() else None
print('done' if phase=='complete-needs-reboot' else 'prepare' if phase in (None,'app-installed') else 'patch')
STATE
)
if [[ "$task_action" == done ]]; then
  print "Установка завершена. Перезагрузите Mac для применения изменений."
  read -k 1
  exit 0
fi
print "OCLP: этап $task_action. Введите пароль администратора в строке Password."
sudo /usr/bin/python3 "$task_stage/install_fork.py" "$task_action" 2>&1 | tee "$task_stage/$task_action.log"
task_result=$?
if (( task_result == 0 )); then
  print "Этап завершён. Сохраните работу и перезагрузите Mac через меню Apple."
  if [[ "$task_action" == prepare ]]; then
    print "После перезапуска снова откройте Continue-OCLP.command на рабочем столе."
  fi
else
  print "Установка остановлена. Не перезагружайте Mac; сохраните текст ошибки."
fi
print "Нажмите любую клавишу, чтобы закрыть окно."
read -k 1
exit $task_result
