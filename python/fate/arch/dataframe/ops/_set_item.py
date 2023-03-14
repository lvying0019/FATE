#
#  Copyright 2019 The FATE Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
import functools
import numpy as np
from .._dataframe import DataFrame
from ..manager.block_manager import BlockType
from ..manager.data_manager import DataManager


def set_item(df: "DataFrame", keys, items, state):
    """
    state: 1 - keys are all new
           2 - keys are all old
    """
    if state == 1:
        _set_new_item(df, keys, items)
    else:
        _set_old_item(df, keys, items)


def _set_new_item(df:"DataFrame", keys, items):
    def _append_single(blocks, item, col_len, bid=None, dm: DataManager=None):
        lines = len(blocks[0])
        ret_blocks = [block for block in blocks]
        ret_blocks.append(dm.blocks[bid].convert_block([[item for idx in range(col_len)] for idx in range(lines)]))

        return ret_blocks

    def _append_multi(blocks, item_list, bid_list=None, dm: DataManager=None):
        lines = len(blocks[0])
        ret_blocks = [block for block in blocks]
        for bid, item in zip(bid_list, item_list):
            ret_blocks.append(dm.blocks[bid].convert_block([[item] for idx in range(lines)]))

        return ret_blocks

    def _append_df(l_blocks, r_blocks, r_blocks_loc=None):
        ret_blocks = [block for block in l_blocks]
        for bid, offset in r_blocks_loc:
            ret_blocks.append(r_blocks[bid][:, [offset]])

        return ret_blocks

    data_manager = df.data_manager
    if isinstance(items, (bool, int, float, np.int32, np.float32, np.int64, np.float64, np.bool)):
        bids = data_manager.append_columns(keys, BlockType.get_block_type(items))
        _append_func = functools.partial(_append_single, item=items, col_len=len(keys), bid=bids[0], dm=data_manager)
        block_table = df.block_table.mapValues(_append_func)

    elif isinstance(items, list):
        if len(keys) != len(items):
            if len(keys) > 1:
                raise ValueError("Must have equal len keys and value when setting with an iterable")
            bids = data_manager.append_columns(keys, BlockType.get_block_type("object"))
            _append_func = functools.partial(_append_single, item=items, col_len=len(keys),
                                             bid=bids[0], dm=data_manager)
        else:
            bids = data_manager.append_columns(keys, [BlockType.get_block_type(items[i]) for i in range(len(keys))])
            _append_func = functools.partial(_append_multi, item_list=items, bid_list=bids, dm=data_manager)
        block_table = df.block_table.mapValues(_append_func)
    elif isinstance(items, DataFrame):
        other_dm = items.data_manager
        operable_fields = other_dm.infer_operable_field_names()
        operable_blocks_loc = other_dm.loc_block(operable_fields)
        block_types = [other_dm.blocks[bid].block_type for bid, _ in operable_blocks_loc]
        if len(keys) != len(operable_fields):
            raise ValueError("Setitem with rhs=DataFrame must have equal len keys")
        data_manager.append_columns(keys, block_types)

        _append_func = functools.partial(_append_df, r_blocks_loc=operable_blocks_loc)
        block_table = df.block_table.join(items.block_table, _append_func)
    else:
        """
        assume items is distributed tensor, and has an equal shape of keys
        """
        # TODO: support if DTensor is ok.
        block_table = df.block_table

    df.block_table = block_table


def _set_old_item(df: "DataFrame", keys, items):
    def _replace_single(blocks, item=None, narrow_loc=None, dst_bids=None, dm: DataManager=None):
        ret_blocks = [block for block in blocks]
        for i in range(len(ret_blocks), dm.block_num):
            ret_blocks.append([])

        for bid, offsets in narrow_loc:
            ret_blocks[bid] = ret_blocks[bid][:, offsets]

        lines = len(blocks[0])
        for dst_bid in dst_bids:
            ret_blocks[dst_bid] = dm.blocks[dst_bid].convert_block([[item] for idx in range(lines)])

        return ret_blocks

    def _replace_multi(blocks, item_list=None, narrow_loc=None, dst_bids=None, dm: DataManager=None):
        ret_blocks = [block for block in blocks]
        for i in range(len(ret_blocks), dm.block_num):
            ret_blocks.append([])

        for bid, offsets in narrow_loc:
            ret_blocks[bid] = ret_blocks[bid][:, offsets]

        lines = len(blocks[0])
        for dst_bid, item in zip(dst_bids, item_list):
            ret_blocks[dst_bid] = dm.blocks[dst_bid].convert_block([[item] for idx in range(lines)])

        return ret_blocks

    def _replace_df(l_blocks, r_blocks, narrow_loc=None, dst_bids=None, r_blocks_loc=None, dm: DataManager=None):
        ret_blocks = [block for block in l_blocks]
        for i in range(len(ret_blocks), dm.block_num):
            ret_blocks.append([])

        for bid, offsets in narrow_loc:
            ret_blocks[bid] = ret_blocks[bid][:, offsets]

        for dst_bid, (r_bid, offset) in zip(dst_bids, r_blocks_loc):
            ret_blocks[dst_bid] = r_blocks[r_bid][:, [offset]]

        return ret_blocks

    data_manager = df.data_manager
    if isinstance(items, (bool, int, float, np.int32, np.float32, np.int64, np.float64, np.bool)):
        narrow_blocks, dst_blocks = data_manager.split_columns(keys, BlockType.get_block_type(items))
        replace_func = functools.partial(_replace_single, item=items, narrow_loc=narrow_blocks,
                                         dst_bids=dst_blocks, dm=data_manager)
        block_table = df.block_table.mapValues(replace_func)
    elif isinstance(items, list):
        if len(keys) != len(items):
            if len(keys) > 1:
                raise ValueError("Must have equal len keys and value when setting with an iterable")
            narrow_blocks, dst_blocks = data_manager.split_columns(keys, BlockType.get_block_type("object"))
            replace_func = functools.partial(_replace_single, item=items[0], narrow_loc=narrow_blocks,
                                             dst_bids=dst_blocks, dm=data_manager)
        else:
            narrow_blocks, dst_blocks = data_manager.split_columns(keys,
                                                                   [BlockType.get_block_type(item) for item in items])
            replace_func = functools.partial(_replace_multi, item_list=items, narrow_loc=narrow_blocks,
                                             dst_bids=dst_blocks, dm=data_manager)

        block_table = df.block_table.mapValues(replace_func)
    elif isinstance(items, DataFrame):
        other_dm = items.data_manager
        operable_fields = other_dm.infer_operable_field_names()
        operable_blocks_loc = other_dm.loc_block(operable_fields)
        block_types = [other_dm.blocks[bid].block_type for bid, _ in operable_blocks_loc]
        if len(keys) != len(operable_fields):
            raise ValueError("Setitem with rhs=DataFrame must have equal len keys")
        narrow_blocks, dst_blocks = data_manager.split_columns(keys, block_types)
        replace_func = functools.partial(_replace_df, narrow_loc=narrow_blocks, dst_bids=dst_blocks,
                                         r_blocks_loc=operable_blocks_loc, dm=data_manager)
        block_table = df.block_table.join(items.block_table, replace_func)
    else:
        """
        assume items is distributed tensor, and has an equal shape of keys
        """
        # TODO: support if DTensor is ok.
        block_table = df.block_table

    df.block_table = block_table
