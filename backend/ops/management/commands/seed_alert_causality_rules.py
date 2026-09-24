"""幂等种入默认 L1 因果规则（ops/alert_causality.py DEFAULT_CAUSAL_RULES）。"""

from django.core.management.base import BaseCommand

from ops.alert_causality import ALERT_CODE_DICTIONARY, DEFAULT_CAUSAL_RULES
from ops.models import AlertCausalRule


class Command(BaseCommand):
    help = '种入默认 L1 因果规则与告警码字典统计'

    def handle(self, *args, **options):
        created = 0
        for entry in DEFAULT_CAUSAL_RULES:
            _, is_new = AlertCausalRule.objects.update_or_create(
                code=entry['code'],
                defaults={
                    'name': entry['name'],
                    'description': entry.get('description', ''),
                    'source_alert_codes': entry['source_alert_codes'],
                    'target_alert_codes': entry['target_alert_codes'],
                    'relation_type_code': entry.get('relation_type_code', ''),
                    'direction': entry.get('direction', 'upstream'),
                    'max_hops': entry.get('max_hops', 5),
                    'window_minutes': entry.get('window_minutes', 5),
                    'priority': entry.get('priority', 0),
                },
            )
            if is_new:
                created += 1

        self.stdout.write(
            f'告警码字典 {len(ALERT_CODE_DICTIONARY)} 条；'
            f'L1 因果规则 {len(DEFAULT_CAUSAL_RULES)} 条（新增 {created}）。'
        )
