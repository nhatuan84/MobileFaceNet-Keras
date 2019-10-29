# -*- coding: utf-8 -*-
"""
Created on Mon May 13 14:39:29 2019

@author: TMaysGGS
"""

'''Last updated on 10/28/2019 09:09'''
'''Importing the libraries'''
import math
import tensorflow as tf
from keras import backend as K
from keras.models import Model
from keras.layers import BatchNormalization, Conv2D, PReLU, Input, SeparableConv2D, DepthwiseConv2D, add, Flatten, Dense, Dropout
from keras.engine.topology import Layer
from keras import initializers
from keras.utils import plot_model

NUM_LABELS = 26928

'''Building Block Functions'''
def conv_block(inputs, filters, kernel_size, strides, padding):
    
    channel_axis = 1 if K.image_data_format() == 'channels_first' else -1
    
    Z = Conv2D(filters, kernel_size, strides = strides, padding = padding, use_bias = False)(inputs)
    Z = BatchNormalization(axis = channel_axis)(Z)
    A = PReLU()(Z)
    
    return A

def separable_conv_block(inputs, filters, kernel_size, strides):
    
    channel_axis = 1 if K.image_data_format() == 'channels_first' else -1
    
    Z = SeparableConv2D(filters, kernel_size, strides = strides, padding = "same", use_bias = False)(inputs)
    Z = BatchNormalization(axis = channel_axis)(Z)
    A = PReLU()(Z)
    
    return A

def bottleneck(inputs, filters, kernel, t, s, r = False):
    
    channel_axis = 1 if K.image_data_format() == 'channels_first' else -1
    tchannel = K.int_shape(inputs)[channel_axis] * t
    
    Z1 = conv_block(inputs, tchannel, 1, s, 'same')
    
    Z1 = DepthwiseConv2D(kernel, strides = 1, padding = "same", depth_multiplier = 1, use_bias = False)(Z1)
    Z1 = BatchNormalization(axis = channel_axis)(Z1)
    A1 = PReLU()(Z1)
    
    Z2 = Conv2D(filters, 1, strides = 1, padding = "same", use_bias = False)(A1)
    Z2 = BatchNormalization(axis = channel_axis)(Z2)
    
    if r:
        Z2 = add([Z2, inputs])
    
    return Z2

def inverted_residual_block(inputs, filters, kernel, t, strides, n):
    
    Z = bottleneck(inputs, filters, kernel, t, strides)
    
    for i in range(1, n):
        Z = bottleneck(Z, filters, kernel, t, 1, True)
    
    return Z

def linear_GD_conv_block(inputs, kernel_size, strides):
    
    channel_axis = 1 if K.image_data_format() == 'channels_first' else -1
    
    Z = DepthwiseConv2D(kernel_size, strides = strides, padding = "valid", depth_multiplier = 1, use_bias = False)(inputs)
    Z = BatchNormalization(axis = channel_axis)(Z)
    
    return Z

# Arc Face Loss Layer (Class)
class ArcFaceLossLayer(Layer):
    '''
    Arguments:
        inputs: the input embedding vectors
        class_num: number of classes
        s: scaler value (default as 64)
        m: the margin value (default as 0.5)
    Returns:
        the final calculated outputs
    '''
    def __init__(self, class_num, s = 64., m = 0.5, **kwargs):
        
        self.init = initializers.get('glorot_uniform') # Xavier uniform intializer
        self.class_num = class_num
        self.s = s
        self.m = m
        super(ArcFaceLossLayer, self).__init__(**kwargs)
        
    def build(self, input_shape):
        
        assert len(input_shape[0]) == 2 and len(input_shape[1]) == 2
        self.W = self.add_weight((input_shape[0][-1], self.class_num), initializer = self.init, name = '{}_W'.format(self.name))
        super(ArcFaceLossLayer, self).build(input_shape)
        
    def call(self, inputs, mask = None):
        
        cos_m = math.cos(self.m)
        sin_m = math.sin(self.m)
        mm = sin_m * self.m
        threshold = math.cos(math.pi - self.m)
        
        # features
        X = inputs[0] 
        # 1-D or one-hot label works as mask
        Y_mask = inputs[1] 
        # If Y_mask is not in one-hot form, transfer it to one-hot form.
        if Y_mask.shape[-1] == 1: 
            Y_mask = K.cast(Y_mask, tf.int32)
            Y_mask = K.reshape(K.one_hot(Y_mask, self.class_num), (-1, self.class_num))
        
        X_normed = K.l2_normalize(X, axis = 1) # L2 Normalized X
        self.W = K.l2_normalize(self.W, axis = 0) # L2 Normalized Weights
        
        # cos(theta + m)
        cos_theta = K.dot(X_normed, self.W)
        cos_theta2 = K.square(cos_theta)
        sin_theta2 = 1. - cos_theta2
        sin_theta = K.sqrt(sin_theta2 + K.epsilon())
        cos_tm = self.s * ((cos_theta * cos_m) - (sin_theta * sin_m))
        
        # This condition controls the theta + m should in range [0, pi]
        #   0 <= theta + m < = pi
        #   -m <= theta <= pi - m
        cond_v = cos_theta - threshold
        cond = K.cast(K.relu(cond_v), dtype = tf.bool)
        keep_val = self.s * (cos_theta - mm)
        cos_tm_temp = tf.where(cond, cos_tm, keep_val)
        
        # mask by label
        Y_mask =+ K.epsilon()
        inv_mask = 1. - Y_mask
        s_cos_theta = self.s * cos_theta
        
        output = K.softmax((s_cos_theta * inv_mask) + (cos_tm_temp * Y_mask))
        
        return output
    
    def compute_output_shape(self, input_shape):
        
        return input_shape[0], self.class_num 

'''Building the MobileFaceNet Model'''
def mobile_face_net():
    
    X = Input(shape = (112, 112, 3))
    label = Input((NUM_LABELS, ))

    M = conv_block(X, 64, 3, 2, 'same') # Output Shape: (56, 56, 64) 

    M = separable_conv_block(M, 64, 3, 1) # (56, 56, 64) 
    
    M = inverted_residual_block(M, 64, 3, t = 2, strides = 2, n = 5) # (28, 28, 64) 
    
    M = inverted_residual_block(M, 128, 3, t = 4, strides = 2, n = 1) # (14, 14, 128) 
    
    M = inverted_residual_block(M, 128, 3, t = 2, strides = 1, n = 6) # (14, 14, 128) 
    
    M = inverted_residual_block(M, 128, 3, t = 4, strides = 2, n = 1) # (7, 7, 128) 
    
    M = inverted_residual_block(M, 128, 3, t = 2, strides = 1, n = 2) # (7, 7, 128) 
    
    M = conv_block(M, 512, 1, 1, 'valid') # (7, 7, 512) 
    
    M = linear_GD_conv_block(M, 7, 1) # (1, 1, 512) 
    # kernel_size = 7 for 112 x 112; 4 for 64 x 64
    
    M = conv_block(M, 128, 1, 1, 'valid')
    M = Dropout(rate = 0.1)(M)
    M = Flatten()(M)
    
    M = Dense(128, activation = None, use_bias = False, kernel_initializer = 'glorot_normal')(M) 
    
    Z_L = ArcFaceLossLayer(class_num = NUM_LABELS)([M, label])
    
    model = Model(inputs = [X, label], outputs = Z_L, name = 'mobile_face_net')
    
    return model

model = mobile_face_net()

model.summary()
model.layers

'''Loading the model & re-defining'''
model.load_weights('./Models/MobileFaceNet_train.h5')
# model.load_weights("E:\\Python_Coding\\MobileFaceNet\\model.hdf5")
model.summary()
model.layers

# Re-define the model
model.layers.pop() # Remove the ArcFace Loss Layer
model.layers.pop() # Remove the Label Input Layer
model.summary()

model.layers[-1].outbound_nodes = []
model.outputs = [model.layers[-1].output] # Reset the output
output = model.get_layer(model.layers[-1].name).output
model.input
# The model used for prediction
pred_model = Model(model.input[0], output)
pred_model.summary()
pred_model.save('./Models/MobileFaceNet.h5')
plot_model(pred_model, to_file='pred_model.png')
