from rest_framework import serializers
from .models import CIType, ConfigItem, CIRelation, CostRecord, ResourceRequest, ResourceNode
from django.db.models import Sum

class CITypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CIType
        fields = '__all__'

class ConfigItemSerializer(serializers.ModelSerializer):
    ci_type_name = serializers.CharField(source='ci_type.name', read_only=True)
    ci_type_icon = serializers.CharField(source='ci_type.icon', read_only=True)
    ci_type_color = serializers.CharField(source='ci_type.color', read_only=True)
    relation_count = serializers.SerializerMethodField()

    class Meta:
        model = ConfigItem
        fields = '__all__'

    def get_relation_count(self, obj):
        return obj.outgoing_relations.count() + obj.incoming_relations.count()

class CIRelationSerializer(serializers.ModelSerializer):
    source_name = serializers.CharField(source='source.name', read_only=True)
    target_name = serializers.CharField(source='target.name', read_only=True)
    source_type = serializers.CharField(source='source.ci_type.name', read_only=True)
    target_type = serializers.CharField(source='target.ci_type.name', read_only=True)

    class Meta:
        model = CIRelation
        fields = '__all__'

    def validate(self, attrs):
        source = attrs.get('source') or getattr(self.instance, 'source', None)
        target = attrs.get('target') or getattr(self.instance, 'target', None)
        relation_type = attrs.get('relation_type') or getattr(self.instance, 'relation_type', None)

        if source and target and source.id == target.id:
            raise serializers.ValidationError('Source and target must be different CIs.')

        if source and target and relation_type:
            duplicate_qs = CIRelation.objects.filter(
                source=source,
                target=target,
                relation_type=relation_type,
            )
            if self.instance is not None:
                duplicate_qs = duplicate_qs.exclude(pk=self.instance.pk)
            if duplicate_qs.exists():
                raise serializers.ValidationError('This CI relation already exists.')

        return attrs

class CostRecordSerializer(serializers.ModelSerializer):
    ci_name = serializers.CharField(source='ci.name', read_only=True)
    business_line = serializers.CharField(source='ci.business_line', read_only=True)

    class Meta:
        model = CostRecord
        fields = '__all__'

class ResourceRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceRequest
        fields = '__all__'

class ResourceNodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ResourceNode
        fields = '__all__'
