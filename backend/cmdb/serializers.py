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
