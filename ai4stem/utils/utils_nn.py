import tensorflow
from tensorflow.keras.layers import Conv2D, LeakyReLU, MaxPool2D, Flatten, Dropout, Dense, Input

from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import ModelCheckpoint, EarlyStopping

from tensorflow.keras.models import load_model

import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

# from hyperopt import hp, fmin, tpe, STATUS_OK, Trials
# from hyperopt import space_eval

import os

import csv
import time
from tensorflow.keras.regularizers import L2


from scipy.stats import mode
from scipy import stats

def predict_with_uncertainty(data, model=None, model_type='classification', n_iter=1000):
    """This function allows to calculate the uncertainty of a neural network model using dropout.

    This follows Chap. 3 in Yarin Gal's PhD thesis:
    http://mlg.eng.cam.ac.uk/yarin/thesis/thesis.pdf

    We calculate the uncertainty of the neural network predictions in the three ways proposed in Gal's PhD thesis,
     as presented at pag. 51-54:
    - variation_ratio: defined in Eq. 3.19
    - predictive_entropy: defined in Eq. 3.20
    - mutual_information: defined at pag. 53 (no Eq. number)

    .. codeauthor:: Angelo Ziletti <angelo.ziletti@gmail.com>

    """

    #logger.info("Calculating classification uncertainty.")

    """
    if model is None:
        #logger.info("Using the model from Ziletti et al. Nature Communications, vol. 9, pp. 2775 (2018)")
        model = load_nature_comm_ziletti2018_network()
    """
    # reshaping it according to Theano rule
    # Theano backend uses (nb_sample, channels, height, width)
    # data = reshape_images_to_theano(data) ## AL : WILL NOT WORK
    # data = data.astype('float32')

    # normalize each image separately
    """
    if True:
        #data[ :, :, :] = (data[ :, :, :] - np.amin(data[ :, :, :])) / (
        #            np.amax(data[ :, :, :]) - np.amin(data[ :, :, :]))
        
        for idx in range(data.shape[0]):
            data[idx, :, :, :] = (data[idx, :, :, :] - np.amin(data[idx, :, :, :])) / (
                    np.amax(data[idx, :, :, :]) - np.amin(data[idx, :, :, :]))
        #for idx in range(data.shape[0]):
        #    data[idx, :, :, :] = (data[idx, :, :, :] - np.amin(data[idx, :, :, :])) / (
        #            np.amax(data[idx, :, :, :]) - np.amin(data[idx, :, :, :]))

    print(data.shape)
    """

    labels = []
    results = []
    for idx_iter in range(n_iter):
        if (idx_iter % (int(n_iter) / 10 + 1)) == 0:
            print("Performing forward pass: {0}/{1}".format(idx_iter + 1, n_iter))

        result = model.predict(data)
        label = result.argmax(axis=-1)

        labels.append(label)
        results.append(result)

    results = np.asarray(results)
    prediction = results.mean(axis=0)

    if model_type == 'regression':
        predictive_variance = results.var(axis=0)
        uncertainty = dict(predictive_variance=predictive_variance)

    elif model_type == 'classification':
        # variation ratio
        mode, mode_count = stats.mode(np.asarray(labels))
        variation_ratio = np.transpose(1. - mode_count.mean(axis=0) / float(n_iter))

        # predictive entropy
        # clip values to 1e-12 to avoid divergency in the log
        prediction = np.clip(prediction, a_min=1e-12, a_max=None, out=prediction)
        log_p_class = np.log2(prediction)
        entropy_all_iteration = - np.multiply(prediction, log_p_class)
        predictive_entropy = np.sum(entropy_all_iteration, axis=1)

        # mutual information
        # clip values to 1e-12 to avoid divergency in the log
        results = np.clip(results, a_min=1e-12, a_max=None, out=results)
        p_log_p_all = np.multiply(np.log2(results), results)
        exp_p_omega = np.sum(np.sum(p_log_p_all, axis=0), axis=1)
        mutual_information = predictive_entropy + 1. / float(n_iter) * exp_p_omega

        uncertainty = dict(variation_ratio=variation_ratio, predictive_entropy=predictive_entropy,
                           mutual_information=mutual_information)
    else:
        raise ValueError("Supported model types are 'classification' or 'regression'."
                         "model_type={} is not accepted.".format(model_type))

    return prediction, uncertainty



def decode_preds(data, model, n_iter=1000):

    results = []
    for idx in range(n_iter):
        pred = model.predict(data, batch_size=2048)
        results.append(pred)

    results = np.asarray(results)
    predictions = np.mean(results, axis=0)
    return predictions

def train_and_test_model(model, X_train, y_train, X_val, y_val, savepath_model,
                         epochs=100, batch_size=64, verbose=1, n_iter=1000):

    callbacks_savepath = os.path.join(savepath_model, 'model_it_{}.h5'.format(ITERATION))

    callbacks = []
    monitor = 'val_loss'
    mode = 'min'
    #monitor = 'val_categorical_accuracy'
    #mode = 'max'    
    save_model_per_epoch = ModelCheckpoint(callbacks_savepath, monitor=monitor, verbose=1,
                                       save_best_only=True, mode=mode, period=1)
    callbacks.append(save_model_per_epoch)

    #es = EarlyStopping(monitor=monitor, mode=mode, patience=10)
    #callbacks.append(es)

    # Fit model
    history = model.fit(X_train, y_train, epochs=epochs, batch_size=batch_size,
                        verbose=verbose, validation_data=(X_val, y_val),
                        callbacks=callbacks)

    optimal_model = load_model(callbacks_savepath)


    #train_pred = decode_preds(data=X_train, model=optimal_model, n_iter=n_iter)
    acc_train = 0.0 #accuracy_score(y_true=y_train.argmax(axis=-1), y_pred = train_pred.argmax(axis=-1))

    val_pred = decode_preds(data=X_val, model=optimal_model, n_iter=n_iter)
    np.save(os.path.join(savepath_model, 'it_{}_predictions.npy'.format(ITERATION)), val_pred)
    acc_val = accuracy_score(y_true=y_val.argmax(axis=-1), y_pred = val_pred.argmax(axis=-1))

    return acc_train, acc_val, optimal_model, history



def cnn_model(input_shape=(64, 64, 1), dropout=0.05,
              alpha=0.0, nb_blocks = 3, filter_sizes=[32, 16, 8],
              kernel_size=(3,3), nb_classes=11, l2_value=1e-3):

    if not len(filter_sizes) == nb_blocks:
        raise ValueError("# filters must be compatible with nb_blocks.")

    l2_reg = L2(l2=l2_value)

    inputs = Input(shape=input_shape, name='input')

    convlayer_counter = 0
    pooling_counter = 0
    activation_counter = 0
    dropout_counter = 0
    for i, filters in enumerate(filter_sizes):
        if i == 0:
            x = inputs

        for j in range(2): # repeat the following blocks 2 times

            x = Conv2D(filters=filters, kernel_size=kernel_size, strides=(1, 1),
                       padding='same', kernel_initializer='Orthogonal',
                       data_format="channels_last", kernel_regularizer=l2_reg,
                       name='Convolution_2D_{}'.format(convlayer_counter))(x)
            convlayer_counter += 1
            x = LeakyReLU(alpha=alpha, name='Leaky_ReLU_{}'.format(activation_counter))(x)
            activation_counter += 1
            x = Dropout(rate=dropout, name='Dropout_{}'.format(dropout_counter))(x, training=True)
            dropout_counter += 1

        if not i == (nb_blocks - 1):
            # for last block, no max pooling done
            x = MaxPool2D(pool_size=(2, 2), strides=(2, 2),
                          data_format="channels_last",
                          name='MaxPooling2D_{}'.format(pooling_counter))(x)
            pooling_counter += 1

    x = Flatten(name='Flatten')(x)
    x = Dense(128, name='Dense_1', kernel_regularizer=l2_reg, activation='relu')(x)
    x = Dropout(rate=dropout,
                name='dropout_{}'.format(dropout_counter))(x, training=True)
    outputs = Dense(nb_classes, name='Dense_2', activation='softmax') (x)

    model = tensorflow.keras.Model(inputs, outputs)

    adam = Adam(beta_1=0.9, beta_2=0.999, decay=0.0)

    model.compile(loss='categorical_crossentropy', optimizer=adam, metrics=['categorical_accuracy'])

    return model



def start_training(X_train, X_val, y_train, y_val, 
                   savepath_model=None, params=None):
    if savepath_model == None:
        savepath_model = os.getcwd()
    if params == None:
        params = {"epochs": 5, "batch_size": 64, "alpha": 0.0,
                "kernel_size": (7,7),
                "architecture": (3, [32, 16, 8]),
                "dropout": 0.1,
                "l2_value": 0.0,
                'n_iter':10}
    n_iter = params['n_iter']
    global ITERATION
    ITERATION = 0
    
    
    t_start = time.time()
    
    
    model = cnn_model(input_shape=(64, 64, 1), dropout=params["dropout"], alpha=params["alpha"],
                      nb_blocks=params["architecture"][0], filter_sizes=params["architecture"][1],
                      kernel_size=params["kernel_size"], nb_classes=np.unique(y_val.argmax(axis=-1)).size,
                      l2_value=params['l2_value'])
    
    acc_training, acc_validation, model, history = train_and_test_model(model=model, batch_size=params['batch_size'],
                                                                        epochs=params['epochs'],
                                                                        X_train=X_train, y_train=y_train,
                                                                        X_val=X_val, y_val=y_val, verbose=1,
                                                                        n_iter=n_iter,
                                                                        savepath_model=savepath_model)#1000)
    
    
    for key in history.history:
        np.save(os.path.join(savepath_model, 'it_{}_{}.npy'.format(ITERATION, key)), history.history[key])
    
    
    t_end = time.time()
    eval_time = round(abs(t_start-t_end),3)
    print('Training finished in {}s'.format(eval_time))
