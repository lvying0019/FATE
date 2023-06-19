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
import random

from fate.arch.context.io.data import df


class DataLoader(object):
    def __init__(
        self,
        dataset,
        ctx=None,
        mode="homo",
        role="guest",
        need_align=False,
        sync_arbiter=False,
        batch_size=-1,
        shuffle=False,
        batch_strategy="full",
        random_seed=None,
    ):
        self._ctx = ctx
        self._dataset = dataset
        self._batch_size = batch_size
        if dataset:
            if batch_size == -1:
                self._batch_size = len(dataset)
            else:
                self._batch_size = min(batch_size, len(dataset))
        self._shuffle = shuffle
        self._batch_strategy = batch_strategy
        self._random_seed = random_seed
        self._need_align = need_align
        self._mode = mode
        self._role = role
        self._sync_arbiter = sync_arbiter

        self._init_settings()

    def _init_settings(self):
        if isinstance(self._dataset, df.Dataframe):
            self._dataset = self._dataset.data

        if self._batch_strategy == "full":
            self._batch_generator = FullBatchDataLoader(
                self._dataset,
                self._ctx,
                mode=self._mode,
                role=self._role,
                batch_size=self._batch_size,
                shuffle=self._shuffle,
                random_seed=self._random_seed,
                need_align=self._need_align,
                sync_arbiter=self._sync_arbiter,
            )
        else:
            raise ValueError(f"batch strategy {self._batch_strategy} is not support")

    def next_batch(self, with_index=True):
        batch = next(self._batch_generator)
        if with_index:
            return batch
        else:
            return batch[1:]

    @staticmethod
    def batch_num(self):
        return self._batch_generator.batch_num

    def __next__(self):
        for batch in self._batch_generator:
            yield batch

    def __iter__(self):
        for batch in self._batch_generator:
            yield batch


class FullBatchDataLoader(object):
    def __init__(self, dataset, ctx, mode, role, batch_size, shuffle, random_seed, need_align, sync_arbiter):
        self._dataset = dataset
        self._ctx = ctx
        self._mode = mode
        self._role = role
        self._batch_size = batch_size
        if self._batch_size < 0 and self._role != "arbiter":
            self._batch_size = len(self._dataset)
        self._shuffle = shuffle
        self._random_seed = random_seed
        self._need_align = need_align
        self._sync_arbiter = sync_arbiter

        self._batch_num = None
        self._batch_splits = []  # list of DataFrame
        self._prepare()

    def _prepare(self):
        if self._mode == "homo":
            if self._role == "arbiter":
                batch_info = self._ctx.arbiter.get("batch_info")
                self._batch_size = batch_info["batch_size"]
                self._batch_num = batch_info["batch_num"]
            elif self._role == "guest":
                self._batch_num = (len(self._dataset) + self._batch_size - 1) // self._batch_size
                self._ctx.arbiter.put("batch_num", self._batch_num)
        elif self._mode == "local":
            self._batch_num = (len(self._dataset) + self._batch_size - 1) // self._batch_size
        elif self._mode == "hetero":
            # TODO: index should be align first
            if self._role != "arbiter":
                self._batch_num = (len(self._dataset) + self._batch_size - 1) // self._batch_size
                if self._role == "guest" and self._sync_arbiter:
                    self._ctx.arbiter.put("batch_num", self._batch_num)
            elif self._sync_arbiter:
                self._batch_num = self._ctx.guest.get("batch_num")

        if self._role == "arbiter":
            return

        if self._batch_size == len(self._dataset):
            self._batch_splits.append(self._dataset)
        else:
            if self._mode in ["homo", "local"] or self._role == "guest":
                indexer = list(self._dataset.get_indexer(target="sample_id").collect())
                if self._shuffle:
                    random.seed = self._random_seed
                random.shuffle(indexer)

                for i, iter_ctx in self._ctx.range(self._batch_num):
                    batch_indexer = indexer[self._batch_size * i: self._batch_size * (i + 1)]
                    batch_indexer = self._ctx.computing.parallelize(batch_indexer,
                                                                    include_key=True,
                                                                    partition=self._dataset.block_table.partitions)

                    sub_frame = self._dataset.loc(batch_indexer, preserve_order=True)

                    if self._role == "guest":
                        iter_ctx.hosts.put("batch_indexes", batch_indexer)

                    self._batch_splits.append(sub_frame)
            elif self._mode == "hetero" and self._role == "host":
                for i, iter_ctx in self._ctx.range(self._batch_num):
                    batch_indexes = iter_ctx.guest.get("batch_indexes")
                    sub_frame = self._dataset.loc(batch_indexes, preserve_order=True)
                    self._batch_splits.append(sub_frame)

    def __next__(self):
        if self._role == "arbiter":
            for batch_id in range(self._batch_num):
                yield batch_id, batch_id
            return

        for batch in self._batch_splits:
            if batch.label and batch.weight:
                yield batch.values, batch.label, batch.weight
            elif batch.label:
                yield batch.values, batch.label
            else:
                yield batch.values

    def __iter__(self):
        if self._role == "arbiter":
            for batch_id in range(self._batch_num):
                yield batch_id, batch_id
            return

        for batch in self._batch_splits:
            if batch.label and batch.weight:
                yield batch.values, batch.label, batch.weight
            elif batch.label:
                yield batch.values, batch.label
            else:
                yield batch.values

    @property
    def batch_num(self):
        return self._batch_num
