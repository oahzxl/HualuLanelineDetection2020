# coding: utf8
# Copyright (c) 2019 PaddlePaddle Authors. All Rights Reserve.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import paddle.fluid as fluid
import numpy as np
import importlib
from utils.config import cfg


def softmax_with_loss(logit,
                      label,
                      ignore_mask=None,
                      num_classes=2,
                      weight=None):
    ignore_mask = fluid.layers.cast(ignore_mask, 'float32')
    label = fluid.layers.elementwise_min(
        label, fluid.layers.assign(np.array([num_classes - 1], dtype=np.int32)))
    logit = fluid.layers.transpose(logit, [0, 2, 3, 1])
    logit = fluid.layers.reshape(logit, [-1, num_classes])
    label = fluid.layers.reshape(label, [-1, 1])
    label = fluid.layers.cast(label, 'int64')
    ignore_mask = fluid.layers.reshape(ignore_mask, [-1, 1])
    if weight is None:
        loss, probs = fluid.layers.softmax_with_cross_entropy(
            logit,
            label,
            ignore_index=cfg.DATASET.IGNORE_INDEX,
            return_softmax=True)
    else:
        label = fluid.layers.squeeze(label, axes=[-1])
        label_one_hot = fluid.one_hot(input=label, depth=num_classes)
        if isinstance(weight, list):
            assert len(
                weight
            ) == num_classes, "weight length must equal num of classes"
            weight = fluid.layers.assign(np.array([weight], dtype='float32'))
        elif isinstance(weight, str):
            assert weight.lower(
            ) == 'dynamic', 'if weight is string, must be dynamic!'
            tmp = []
            total_num = fluid.layers.cast(
                fluid.layers.shape(label)[0], 'float32')
            for i in range(num_classes):
                cls_pixel_num = fluid.layers.reduce_sum(label_one_hot[:, i])
                ratio = total_num / (cls_pixel_num + 1)
                tmp.append(ratio)
            weight = fluid.layers.concat(tmp)
            weight = weight / fluid.layers.reduce_sum(weight) * num_classes
        elif isinstance(weight, fluid.layers.Variable):
            pass
        else:
            raise ValueError(
                'Expect weight is a list, string or Variable, but receive {}'.
                format(type(weight)))
        weight = fluid.layers.reshape(weight, [1, num_classes])
        weighted_label_one_hot = fluid.layers.elementwise_mul(
            label_one_hot, weight)
        probs = fluid.layers.softmax(logit)
        # weighted_label_one_hot = weighted_label_one_hot*(1-probs)
        loss = fluid.layers.cross_entropy(
            probs,
            weighted_label_one_hot,
            soft_label=True,
            ignore_index=cfg.DATASET.IGNORE_INDEX)
        weighted_label_one_hot.stop_gradient = True

    loss = loss * ignore_mask
    avg_loss = fluid.layers.mean(loss) / (fluid.layers.mean(ignore_mask) + cfg.MODEL.DEFAULT_EPSILON)

    label.stop_gradient = True
    ignore_mask.stop_gradient = True
    return avg_loss


def inter_loss(logit, label, ignore_mask=None, num_classes=2, weight=None):
    ignore_mask = fluid.layers.cast(ignore_mask, 'float32')

    logit = fluid.layers.transpose(logit, [0, 2, 3, 1])
    logit = fluid.layers.reshape(logit, [-1, num_classes])
    label = fluid.layers.reshape(label, [-1, 1])
    label = fluid.layers.cast(label, 'int64')

    def get_std(target):
        flag = fluid.layers.ones_like(label) * target
        label_flag = fluid.layers.cast(fluid.layers.equal(fluid.layers.cast(label, "float32"),
                                                          fluid.layers.cast(flag, "float32")), "float32")
        label_sum = fluid.layers.cast(fluid.layers.reduce_sum(label_flag), "float32")
        zero = fluid.layers.fill_constant([1], "float32", 0)

        def not_zero():
            out = fluid.layers.cast(fluid.layers.reduce_sum(
                fluid.layers.elementwise_mul(label_flag, fluid.layers.cast(logit, "float32")), dim=0), "float32")
            out = out / label_sum
            out = (logit - out) ** 2
            out = fluid.layers.elementwise_mul(fluid.layers.cast(out, "float32"),
                                               fluid.layers.cast(label_flag, "float32"))
            out = fluid.layers.reduce_sum(out) / label_sum / 19
            return out
        def is_zero():
            return fluid.layers.fill_constant([1], "float32", 0)

        l_std = fluid.layers.cond(
            fluid.layers.equal(label_sum, zero),
            is_zero,
            not_zero
        )
        return l_std

    def cond(j, num, label_std_):
        return j < num

    def body(j, num, label_std_):
        # 计算过程是对输入参数i进行自增操作，即 i = i + 1
        label_std_ += get_std(j)
        j = j + 1
        return j, num, label_std_

    label_std = fluid.layers.fill_constant([1], "float32", 0)
    i = fluid.layers.fill_constant(shape=[1], dtype='int32', value=1)  # 循环计数器
    n = fluid.layers.fill_constant(shape=[1], dtype='int32', value=20)  # 循环次数
    _, _, label_std = fluid.layers.while_loop(cond=cond, body=body, loop_vars=[i, n, label_std])
    # fluid.layers.Print(label_std, message="std: ")
    avg_loss = label_std / 19

    label.stop_gradient = True
    label_std.stop_gradient = True

    ignore_mask.stop_gradient = True
    return avg_loss


def lane_width_loss(logit,
                    label,
                    ignore_mask=None,
                    num_classes=2,
                    weight=None):
    ignore_mask = fluid.layers.cast(ignore_mask, 'float32')

    logit = fluid.layers.transpose(logit, [0, 2, 3, 1])
    logit = fluid.layers.reshape(logit, [-1, num_classes])
    label = fluid.layers.reshape(label, [-1, 1])
    label = fluid.layers.cast(label, 'int32')

    new_label = fluid.layers.zeros_like(label)
    flag = fluid.layers.ones_like(label)

    new_label = fluid.layers.elementwise_add(new_label, fluid.layers.elementwise_mul(
        fluid.layers.cast(fluid.layers.greater_equal(x=label, y=flag * 1), 'int32'),
        fluid.layers.cast(fluid.layers.less_equal(x=label, y=flag * 4), 'int32')))
    new_label = fluid.layers.elementwise_add(new_label, 2 * fluid.layers.elementwise_mul(
        fluid.layers.cast(fluid.layers.greater_equal(x=label, y=flag * 5), 'int32'),
        fluid.layers.cast(fluid.layers.less_equal(x=label, y=flag * 10), 'int32')))
    new_label = fluid.layers.elementwise_add(new_label, 3 * (fluid.layers.elementwise_add(
        fluid.layers.elementwise_mul(fluid.layers.cast(fluid.layers.greater_equal(x=label, y=flag * 11), 'int32'),
                                     fluid.layers.cast(fluid.layers.less_equal(x=label, y=flag * 12), 'int32')),
        fluid.layers.cast(fluid.layers.equal(x=label, y=flag * 19), 'int32'))))
    new_label = fluid.layers.elementwise_add(new_label, 4 * fluid.layers.elementwise_mul(
        fluid.layers.cast(fluid.layers.greater_equal(x=label, y=flag * 13), 'int32'),
        fluid.layers.cast(fluid.layers.less_equal(x=label, y=flag * 18), 'int32')))

    label = fluid.layers.cast(new_label, 'int64')

    ignore_mask = fluid.layers.reshape(ignore_mask, [-1, 1])
    if weight is None:
        loss, probs = fluid.layers.softmax_with_cross_entropy(
            logit,
            label,
            ignore_index=cfg.DATASET.IGNORE_INDEX,
            return_softmax=True)
    else:
        label = fluid.layers.squeeze(label, axes=[-1])
        label_one_hot = fluid.one_hot(input=label, depth=num_classes)
        if isinstance(weight, list):
            assert len(
                weight
            ) == num_classes, "weight length must equal num of classes"
            weight = fluid.layers.assign(np.array([weight], dtype='float32'))
        elif isinstance(weight, str):
            assert weight.lower(
            ) == 'dynamic', 'if weight is string, must be dynamic!'
            tmp = []
            total_num = fluid.layers.cast(
                fluid.layers.shape(label)[0], 'float32')
            for i in range(num_classes):
                cls_pixel_num = fluid.layers.reduce_sum(label_one_hot[:, i])
                ratio = total_num / (cls_pixel_num + 1)
                tmp.append(ratio)
            weight = fluid.layers.concat(tmp)
            weight = weight / fluid.layers.reduce_sum(weight) * num_classes
        elif isinstance(weight, fluid.layers.Variable):
            pass
        else:
            raise ValueError(
                'Expect weight is a list, string or Variable, but receive {}'.
                format(type(weight)))
        weight = fluid.layers.reshape(weight, [1, num_classes])
        weighted_label_one_hot = fluid.layers.elementwise_mul(
            label_one_hot, weight)
        probs = fluid.layers.softmax(logit)
        loss = fluid.layers.cross_entropy(
            probs,
            weighted_label_one_hot,
            soft_label=True,
            ignore_index=cfg.DATASET.IGNORE_INDEX)
        weighted_label_one_hot.stop_gradient = True

    loss = loss * ignore_mask
    avg_loss = fluid.layers.mean(loss) / (fluid.layers.mean(ignore_mask) + cfg.MODEL.DEFAULT_EPSILON)
    new_label.stop_gradient = True
    label.stop_gradient = True
    ignore_mask.stop_gradient = True
    return avg_loss


# to change, how to appicate ignore index and ignore mask
def dice_loss(logit, label, ignore_mask=None, epsilon=0.00001):
    if logit.shape[1] != 1 or label.shape[1] != 1 or ignore_mask.shape[1] != 1:
        raise Exception(
            "dice loss is only applicable to one channel classfication")
    ignore_mask = fluid.layers.cast(ignore_mask, 'float32')
    logit = fluid.layers.transpose(logit, [0, 2, 3, 1])
    label = fluid.layers.transpose(label, [0, 2, 3, 1])
    label = fluid.layers.cast(label, 'int64')
    ignore_mask = fluid.layers.transpose(ignore_mask, [0, 2, 3, 1])
    logit = fluid.layers.sigmoid(logit)
    logit = logit * ignore_mask
    label = label * ignore_mask
    reduce_dim = list(range(1, len(logit.shape)))
    inse = fluid.layers.reduce_sum(logit * label, dim=reduce_dim)
    dice_denominator = fluid.layers.reduce_sum(
        logit, dim=reduce_dim) + fluid.layers.reduce_sum(
            label, dim=reduce_dim)
    dice_score = 1 - inse * 2 / (dice_denominator + epsilon)
    label.stop_gradient = True
    ignore_mask.stop_gradient = True
    return fluid.layers.reduce_mean(dice_score)


def bce_loss(logit, label, ignore_mask=None):
    if logit.shape[1] != 1 or label.shape[1] != 1 or ignore_mask.shape[1] != 1:
        raise Exception("bce loss is only applicable to binary classfication")
    label = fluid.layers.cast(label, 'float32')
    loss = fluid.layers.sigmoid_cross_entropy_with_logits(
        x=logit,
        label=label,
        ignore_index=cfg.DATASET.IGNORE_INDEX,
        normalize=True)  # or False
    loss = fluid.layers.reduce_sum(loss)
    label.stop_gradient = True
    ignore_mask.stop_gradient = True
    return loss


def multi_softmax_with_loss(logits,
                            label,
                            ignore_mask=None,
                            num_classes=2,
                            weight=None):
    if isinstance(logits, tuple):
        avg_loss = 0
        for i, logit in enumerate(logits):
            if label.shape[2] != logit.shape[2] or label.shape[
                    3] != logit.shape[3]:
                logit_label = fluid.layers.resize_nearest(label, logit.shape[2:])
            else:
                logit_label = label
            logit_mask = (logit_label.astype('int32') !=
                          cfg.DATASET.IGNORE_INDEX).astype('int32')
            loss = softmax_with_loss(logit, logit_label, logit_mask, num_classes, weight=weight)
            avg_loss += cfg.MODEL.MULTI_LOSS_WEIGHT[i] * loss
    else:
        avg_loss = softmax_with_loss(
            logits, label, ignore_mask, num_classes, weight=weight)
    return avg_loss


def multi_dice_loss(logits, label, ignore_mask=None):
    if isinstance(logits, tuple):
        avg_loss = 0
        for i, logit in enumerate(logits):
            if label.shape[2] != logit.shape[2] or label.shape[
                    3] != logit.shape[3]:
                logit_label = fluid.layers.resize_nearest(label, logit.shape[2:])
            else:
                logit_label = label
            logit_mask = (logit_label.astype('int32') !=
                          cfg.DATASET.IGNORE_INDEX).astype('int32')
            loss = dice_loss(logit, logit_label, logit_mask)
            avg_loss += cfg.MODEL.MULTI_LOSS_WEIGHT[i] * loss
    else:
        avg_loss = dice_loss(logits, label, ignore_mask)
    return avg_loss


def multi_bce_loss(logits, label, ignore_mask=None):
    if isinstance(logits, tuple):
        avg_loss = 0
        for i, logit in enumerate(logits):
            if label.shape[2] != logit.shape[2] or label.shape[
                    3] != logit.shape[3]:
                logit_label = fluid.layers.resize_nearest(label, logit.shape[2:])
            else:
                logit_label = label
            logit_mask = (logit_label.astype('int32') !=
                          cfg.DATASET.IGNORE_INDEX).astype('int32')
            loss = bce_loss(logit, logit_label, logit_mask)
            avg_loss += cfg.MODEL.MULTI_LOSS_WEIGHT[i] * loss
    else:
        avg_loss = bce_loss(logits, label, ignore_mask)
    return avg_loss

def focal_loss(pred, label, ignore_mask=None, num_classes=2, weight=None):
    ignore_mask = fluid.layers.cast(ignore_mask, 'float32')
    ignore_mask = fluid.layers.reshape(ignore_mask, [-1, 1])
    label = fluid.layers.reshape(label, [-1, 1])
    label = fluid.layers.cast(label, 'int64')
    one_hot = fluid.layers.one_hot(label, num_classes)
    pred = fluid.layers.transpose(pred, [0, 2, 3, 1])
    pred = fluid.layers.reshape(pred, [-1, num_classes])
    pred = fluid.layers.softmax(pred)
    prob = one_hot * pred
    cross_entropy = one_hot * fluid.layers.log(pred)
    cross_entropy = fluid.layers.reduce_sum(cross_entropy, dim=-1)
    sum = fluid.layers.sum(cross_entropy)
    weight = -1.0 * one_hot * (1.0 - pred)
    weight = fluid.layers.reduce_sum(weight, dim=-1)
    loss = weight * cross_entropy
    loss = loss * ignore_mask
    avg_loss = fluid.layers.mean(loss) / (fluid.layers.mean(ignore_mask) + cfg.MODEL.DEFAULT_EPSILON)
    label.stop_gradient = True
    ignore_mask.stop_gradient = True

    return avg_loss