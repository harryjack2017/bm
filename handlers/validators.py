from conf import enum


class Validators:
    schema_mobile_flow = {
        'type': 'object',
        'required': ['mobile_no', 'flow'],
        'properties': {
            'mobile_no': {
                'type': 'string',
                'minLength': 11
            },
            'flow': {
                'type': 'string',
                'minLength': 1
            }
        }
    }

    schema_gas_card_account_info = {
        'type': 'object',
        'required': ['province', 'operator', 'card_no'],
        'properties': {
            'province': {
                'enum': enum.PROVINCES
            },
            'operator': {
                'enum': enum.OPERATORS
            },
            'card_no': {
                'minLength': 16,
                'maxLength': 19
            }
        }
    }

    schema_gas_card_pay_bill = {
        'type': 'object',
        'required': ['item_id', 'gas_card_tel', 'gas_card_name','card_no'],
        'properties': {
            'item_id': {
                'type': 'string',
                'minLength': 1
            },
            'gas_card_tel': {
                'type': 'string',
                'minLength': 11
            },
            'gas_card_name': {
                'type': 'string',
                'minLength': 1
            },
            'card_no': {
                'minLength': 16,
                'maxLength': 19
            }
        }
    }